import type { InstitutionalDailyData, OfficialEventsData, StockOverviewData } from '../types'
import { formatResearchDate, formatResearchDateTime } from '../stockResearch'
import { formatTableVolume, formatTableVolumeShares } from '../units'

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
  multi_session_institutional_evidence_missing: '缺少可核對的多個交易日法人原件',
  trading_session_source_not_admitted: '缺少已核對的交易日基準',
  strategy_input_sources_not_admitted: '策略所需法人、成交額與族群資料尚待核對',
  strategy_time_evidence_not_verified: '策略輸入與結果的時間證據尚未驗收',
  industry_membership_not_verified: '既有族群關聯待重新核實',
  strategy_result_missing: '截止日期以前沒有這個版本的策略結果',
  strategy_result_before_cutoff: '既有策略結果早於本次截止日期',
  event_capture_consumer_not_verified: '官方事件原件與讀取結果尚待核對',
  event_source_time_not_verified: '事件來源與發布／事件時間尚未完整驗證',
  event_capture_not_enabled: '伺服器尚未明示啟用官方除權息預告取得操作',
  event_capture_configuration_invalid: '伺服器取得設定無效，尚未啟用',
  event_exchange_not_supported: '本區塊目前僅支援上市（TWSE）官方預告',
  event_invalid_symbol: '標的代號尚待核對',
  event_memory_capture_missing: '尚未取得本次官方除權息預告',
  event_shared_cutoff_missing: '尚無共同研究截止日期；取得的觀測日期不會自動補成截止日期',
  event_observation_after_cutoff: '本次觀測日晚於研究截止，無法判斷截止當時已知哪些預告',
  event_capture_in_progress: '同一程序正在取得官方預告，請稍後讀取',
  event_evidence_invalid: '官方預告原件、來源或版本無法完整核對',
  event_capture_failed: '本次官方預告取得失敗，尚無可採用的原件',
  event_capture_request_failed: '本次取得操作未成功，請確認伺服器連線後再操作',
  daily_exchange_not_supported: '本區塊目前僅支援上櫃（TPEx）原件',
  daily_shared_cutoff_missing: '尚無共同研究截止日期',
  daily_capture_not_configured: '尚未設定本地單日法人原件',
  daily_invalid_configuration: '本地原件設定尚待核對',
  daily_invalid_symbol: '標的代號尚待核對',
  daily_after_cutoff: '設定的原件資料日晚於研究截止日期，本次不採用',
  daily_evidence_invalid: '單日法人原件無法完整驗證',
  daily_configured_date_before_cutoff: '設定的原件資料日早於研究截止日期；尚未確認截至日前最新資料',
  selected_row_missing: '原件中沒有這個標的的唯一資料列',
  selected_row_duplicate: '原件中這個標的資料列重複',
  payload_date_mismatch: '原件資料日與設定日期不一致',
}

export function overviewReason(reason: string): string {
  if (reason.startsWith('selected_symbol_missing:')) return '本次官方預告中缺少這個標的；無法據此宣稱沒有事件'
  if (reason.startsWith('http_status:')) return '官方預告來源本次未成功回應，沒有自動重試'
  if (reason.startsWith('purpose_not_admitted:')) return '官方預告的來源使用條件未通過核對'
  if (reason === 'selected_event_duplicate') return '本次官方預告含重複事件，全部拒用'
  if (reason === 'selected_event_class_unknown') return '本次官方預告事件類型無法核對'
  if (reason.startsWith('receipt_mismatch:')) return '擷取紀錄與原件、來源或版本不一致'
  if (reason.startsWith('selected_')) return REASONS[reason] ?? '選中標的的來源欄位無法核對'
  if (reason === 'invalid_share_quantity' || reason === 'negative_gross_quantity') return '選中標的的法人股數或加總無法核對'
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

function exactShares(value: string): string {
  // Format the canonical integer text directly, preserving every digit beyond
  // Number.MAX_SAFE_INTEGER. No Number conversion or share-to-lot rounding.
  if (!/^(?:0|-?[1-9][0-9]*)$/.test(value)) return '待核對'
  return value.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

export function InstitutionalDaily({ data }: { data?: InstitutionalDailyData }) {
  const row = data?.status === 'available' ? data.row : null
  const provenance = row ? data?.provenance : null
  return <section className="panel overview-institutional-daily"><h3>單日法人原件</h3>
    {row && provenance ? <>
      <p>{row.company_name}（{row.symbol}） · 資料日 {formatResearchDate(row.date)} · 單位：股</p>
      <p className="small-note">僅核對本次設定的單日原件與選中標的；不代表完整市場或截至日前最新資料。</p>
      <div className="table-wrap"><table><caption>法人買進、賣出與淨買賣超（股）；正值為買超、負值為賣超。</caption><thead><tr><th>法人</th><th>買進</th><th>賣出</th><th>淨買賣超</th></tr></thead><tbody>
        {(['foreign', 'trust', 'dealer'] as const).map((key) => <tr key={key}><td>{row.investors[key].label}</td><td>{exactShares(row.investors[key].buy)}</td><td>{exactShares(row.investors[key].sell)}</td><td>{exactShares(row.investors[key].net)}</td></tr>)}
        <tr><th colSpan={3}>三類法人淨買賣超合計</th><td>{exactShares(row.total_net)}</td></tr>
      </tbody></table></div>
      <p className="small-note">來源 <a href={provenance.endpoint} target="_blank" rel="noreferrer">證券櫃檯買賣中心 · 上櫃股票三大法人買賣明細資訊</a>；擷取 {formatResearchDateTime(provenance.captured_at)}。本地原件與數值一致；歷史當時可得（PIT）未支援。</p>
      {data?.attribution && <p className="small-note">資料提供：{data.attribution.owner.data_provider} · {data.attribution.owner.attribution_year} · <a href={data.attribution.owner.license_url} target="_blank" rel="noreferrer">政府資料開放授權條款</a></p>}
      <details className="technical-details"><summary>查看法人原件日期、來源版本與雜湊</summary>
        <div className="overview-provenance">原始資料日 {row.source_date} · 原件列序 {row.row_ordinal} · {data?.version}</div>
        <div className="overview-provenance">來源版本 {provenance.source_version} · registry {provenance.registry_version} · manifest {provenance.manifest_digest}</div>
        <div className="overview-provenance">原件 SHA-256 {provenance.body_sha256} · 擷取紀錄 SHA-256 {provenance.receipt_sha256}</div>
        <div className="overview-provenance">擷取時間原值 {provenance.captured_at}</div>
      </details>
    </> : <div className="data-gap">尚無可核對的單日法人原件。</div>}
    <Reasons reasons={data?.reasons ?? ['daily_capture_not_configured']} />
    <p className="small-note">最近 5／20 交易日法人窗口仍不可用；缺少交易日基準與多日原件。缺值不作 0，融資不併入三大法人。</p>
  </section>
}

export function OfficialEvents({ data, onCapture, busy = false, requestFailure }: {
  data: OfficialEventsData; onCapture?: () => void; busy?: boolean; requestFailure?: string
}) {
  const provenance = data.status === 'available' ? data.provenance : null
  return <section className="panel overview-official-events"><h3>官方除權息預告</h3>
    <p className="small-note">明示取得後，原件只保留在本次伺服器程序記憶體。已有原件時讀取同一次觀測；重新取得需重新啟動伺服器，未確認最新資料。</p>
    {data.can_capture && onCapture && <button type="button" className="secondary-button" disabled={busy} onClick={onCapture}>{busy ? '正在取得官方預告…' : data.cache_present ? '讀取本次官方除權息預告' : '取得本次官方除權息預告'}</button>}
    {requestFailure && <div className="data-gap" role="alert">{overviewReason(requestFailure)}</div>}
    <Reasons reasons={data.reasons} />
    {data.observed_date && <p>本次觀測日（臺北）：{formatResearchDate(data.observed_date)}{data.status !== 'available' && '；請將研究截止日期設為此日或較晚日期，再核對本次觀測。'}</p>}
    {provenance && <>
      <div className="table-wrap"><table><caption>本次選中標的的官方除權息預告；事件日為生效日，保留未來日期。</caption><thead><tr><th>標的</th><th>預告類型</th><th>生效日期</th></tr></thead><tbody>{data.rows.map((row) => <tr key={`${row.symbol}-${row.event_date}-${row.kind}`}><td>{row.company_name}（{row.symbol}）</td><td>{row.label}</td><td>{formatResearchDate(row.event_date)}</td></tr>)}</tbody></table></div>
      <p className="small-note">來源：臺灣證券交易所 · 上市除權除息預告表 · <a href={provenance.endpoint} target="_blank" rel="noreferrer">查看官方公告資料集</a>；連結為整份清單（資料 feed），未提供單則原文。</p>
      {data.attribution && <p className="small-note">資料提供：{data.attribution.owner.name} · 授權 {data.attribution.terms.value} · <a href="https://data.gov.tw/license" target="_blank" rel="noreferrer">政府資料開放授權條款</a></p>}
      <details className="technical-details"><summary>查看官方預告觀測、來源版本與雜湊</summary>
        <div className="overview-provenance">擷取觀測時間 {formatResearchDateTime(provenance.captured_at)} · 原值 {provenance.captured_at} · {data.version}</div>
        {data.rows.map((row) => <div className="overview-provenance" key={row.row_ordinal}>{row.symbol} · 原始民國生效日期 {row.source_date} · 原始分類 {row.source_classification} · 原件列序 {row.row_ordinal}</div>)}
        <div className="overview-provenance">來源版本 {provenance.source_version} · registry {provenance.registry_version} · manifest {provenance.manifest_digest}</div>
        <div className="overview-provenance">原件 SHA-256 {provenance.body_sha256} · 擷取紀錄 SHA-256 {provenance.receipt_sha256}</div>
      </details>
    </>}
    <p className="small-note">發布、首次可得與修訂時間均未知；觀測時間不代表發布時間，也不證歷史當時已知。僅核對名稱、代號、生效日期與除權息類型，未驗金融數值，不推論價格影響。</p>
  </section>
}

export function StockOverview({ data, onNews, onCaptureEvents, capturingEvents, eventRequestFailure }: {
  data: StockOverviewData; onNews: () => void; onCaptureEvents?: () => void; capturingEvents?: boolean; eventRequestFailure?: string
}) {
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
          <div className="stock-quote-grid"><div><span>最新可用收盤（報價幣別元）</span><strong>{number(latest.close)}</strong></div><div><span>成交量（張）</span><strong>{formatTableVolume(latest.volume, latest.source, latest.volume_exact) || '數值或單位待核實'}</strong></div><div><span>資料日</span><strong>{formatResearchDate(latest.date)}</strong></div></div>
          <div className="overview-ohlc"><span>開 {number(latest.open)}</span><span>高 {number(latest.high)}</span><span>低 {number(latest.low)}</span><span>收 {number(latest.close)}</span></div>
          <p className="small-note">成交額（來源計價單位）：{number(latest.turnover, 0)}{latest.turnover_status !== 'available' && `；原件${latest.turnover_reason === 'missing' ? '缺少成交額' : '成交額無效'}，未補零。`}</p>
          <p className="small-note">來源 <a href={latest.provenance.endpoint} target="_blank" rel="noreferrer">臺灣證券交易所 · STOCK_DAY_ALL</a>；擷取 {formatResearchDateTime(latest.provenance.captured_at)}。本地原件與數值一致，不代表來源真偽或歷史可得性已驗證。</p>
          <details className="technical-details"><summary>查看價格視窗與來源版本</summary>
            <div>總覽版本 {data.version} · 來源版本 {latest.provenance.source_version} · registry {latest.provenance.registry_version}</div>
            <div className="table-wrap"><table><caption>原始價格（各標的報價幣別的元）與成交量（股）；成交額為來源計價單位，空白表示不可用。</caption><thead><tr><th>日期</th><th>開</th><th>高</th><th>低</th><th>收</th><th>成交量</th><th>成交額</th></tr></thead><tbody>{price.bars.map((bar) => <tr key={bar.date}><td>{formatResearchDate(bar.date)}</td><td>{number(bar.open)}</td><td>{number(bar.high)}</td><td>{number(bar.low)}</td><td>{number(bar.close)}</td><td>{formatTableVolumeShares(bar.volume, bar.source, bar.volume_exact)}</td><td>{bar.turnover == null ? '' : number(bar.turnover, 0)}</td></tr>)}</tbody></table></div>
            {price.bars.map((bar) => <div className="overview-provenance" key={bar.date}>{bar.date} · raw {bar.provenance.raw_payload_id} · 原件 SHA-256 {bar.provenance.body_sha256} · 擷取紀錄 SHA-256 {bar.provenance.receipt_sha256} · 資料時間原值 {bar.data_as_of} · 收集時間原值 {bar.collected_at ?? '未提供'}</div>)}
          </details>
        </> : <div className="data-gap">尚無來源與數值已核對的價格。其餘研究入口可繼續使用。</div>}
        <Reasons reasons={price.reasons} />
        {price.rejected.length > 0 && <details className="technical-details"><summary>未採用 {price.rejected.length} 筆行情的日期與原因</summary>{price.rejected.map((row, index) => <div key={`${row.date}-${index}`}>{formatResearchDate(row.date)}：{overviewReason(row.reason)}（{row.reason}）</div>)}</details>}
      </section>
      <section className="panel"><h3>外資／投信／自營商</h3><div className="badge">資料不足</div><p>最近 5／20 交易日淨買賣超與趨勢尚不可用。</p><Reasons reasons={data.institutional.reasons} /><p className="small-note">各法人獨立計算的來源與交易日條件尚未滿足；缺值不作 0，融資不併入三大法人。</p></section>
      <InstitutionalDaily data={data.institutional_daily} />
      <section className="panel overview-conditions"><h3>研究條件</h3>{data.conditions.map((condition) => <div className="overview-condition" key={condition.strategy}><div className="position-head"><strong>{condition.label}</strong><span className="badge">{condition.status === 'met' ? '成立' : condition.status === 'not_met' ? '未成立' : '資料不足'}</span></div><p className="small-note">既有結果日期 {formatResearchDate(condition.signal_date)}</p><Reasons reasons={condition.reasons} /><details className="technical-details"><summary>查看策略版本</summary>{condition.strategy} · 版本 {condition.version ?? '尚無可核對結果'}</details></div>)}<p className="small-note">沿用既有固定規則；輸入需求不等於條件成立，仍需補齊資料後才能形成完整交易計畫。</p></section>
      <OfficialEvents data={data.events} onCapture={onCaptureEvents} busy={capturingEvents} requestFailure={eventRequestFailure} />
      <section className="panel"><h3>新聞與公告入口</h3><p>保留既有來源連結、發布與事件時間。</p><button type="button" className="secondary-button" onClick={onNews}>查看新聞與公告</button><p className="small-note">新聞採已核對的發布／事件時間截至；未知時間或超過截止的項目不混入本次清單。</p></section>
    </div>
    <details className="technical-details"><summary>研究範圍與總覽版本</summary>總覽版本 {data.version}。M1-P3b 包含資料日期截止、可追溯的原始價格視窗、設定的上櫃單日法人原件與明示取得的上市除權息預告；完整 M1 的法人窗口與研究條件尚未完成。事件只支持本次選中觀測，歷史當時可得（PIT）未支援。</details>
  </section>
}
