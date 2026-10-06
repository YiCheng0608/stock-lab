import type { Instrument, InstitutionalDailyData, InstitutionalWindowsData, OfficialEventsData, StockOverviewData } from '../types'
import { memoryPriceCaptureReady, PRICE_HEADERS, PRICE_SYMBOL_NAMES, priceMemoryInstrumentSupported, priceSourcePins, validStockPriceMemoryRead } from '../stockPriceMemoryRead'
import { formatResearchDate, formatResearchDateTime } from '../stockResearch'
import { formatCanonicalShareLots, formatCanonicalShares, formatTableVolume, formatTableVolumeShares } from '../units'

const REASONS: Record<string, string> = {
  price_memory_capture_missing: '尚未載入本次官方單日行情。',
  price_cutoff_not_supported: '此來源只支持 2026/10/5、2026/10/6；請明示套用其中一日。',
  price_capture_not_enabled: '伺服器尚未明示啟用此官方行情載入。',
  price_instrument_not_supported: '此政策只支援已核准的上櫃普通股。',
  price_external_policy_pins_mismatch: '此官方行情的授權版本設定待核實。',
  price_capture_busy: '官方行情正在載入。',
  price_body_version_mismatch: '來源原件版本已變更，未採用數值。',
  window_capture_not_enabled: '伺服器尚未明示啟用法人窗口載入。',
  window_capture_configuration_invalid: '法人窗口設定無效，尚未啟用。',
  window_market_or_symbol_not_supported: '目前只支持上櫃 3105、6488。',
  window_cutoff_not_supported: '所選日期不在本次法人窗口的支持截止範圍；不沿用其他截止的數值。',
  window_memory_capture_missing: '尚未載入本次法人窗口。',
  window_capture_busy: '伺服器正在載入法人窗口，請稍後讀取。',
  window_capture_failed: '本次法人窗口載入失敗；已有嘗試不自動重試。',
  window_memory_evidence_invalid: '本次法人原件無法完整核對。',
  window_capture_request_failed: '法人窗口請求失敗；請核對伺服器狀態後讀取。',
  institutional_window_expected_dates_missing: '窗口缺少所需交易日原件；缺值不作 0。',
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

export function InstitutionalDaily({ data, windowsPresent = false }: { data?: InstitutionalDailyData; windowsPresent?: boolean }) {
  const row = data?.status === 'available' ? data.row : null
  const provenance = row ? data?.provenance : null
  const unitKnown = data?.unit === 'shares' && row?.unit === 'shares' && data.quantity_encoding === 'canonical_integer_string'
  const lots = (value: unknown, gross = false) => unitKnown ? formatCanonicalShareLots(value, 1, gross) ?? '待核對' : '單位待核實'
  const original = (value: unknown, gross = false) => unitKnown ? formatCanonicalShares(value, 1, gross) ?? '待核對' : '單位待核實'
  return <section className="panel overview-institutional-daily"><h3>單日法人原件</h3>
    {row && provenance ? <>
      <p>{row.company_name}（{row.symbol}） · 資料日 {formatResearchDate(row.date)} · 單位：{unitKnown ? '張' : '來源單位待核實'}</p>
      <p className="small-note">僅核對本次設定的單日原件與選中標的；不代表完整市場或截至日前最新資料。</p>
      <div className="table-wrap"><table><caption>法人買進、賣出與淨買賣超（{unitKnown ? '張' : '單位待核實'}）；正值為買超、負值為賣超。</caption><thead><tr><th>法人</th><th>買進</th><th>賣出</th><th>淨買賣超</th></tr></thead><tbody>
        {(['foreign', 'trust', 'dealer'] as const).map((key) => <tr key={key}><td>{row.investors[key].label}</td><td>{lots(row.investors[key].buy, true)}</td><td>{lots(row.investors[key].sell, true)}</td><td>{lots(row.investors[key].net)}</td></tr>)}
        <tr><th colSpan={3}>三類法人淨買賣超合計</th><td>{lots(row.total_net)}</td></tr>
      </tbody></table></div>
      <p className="small-note">來源 <a href={provenance.endpoint} target="_blank" rel="noreferrer">證券櫃檯買賣中心 · 上櫃股票三大法人買賣明細資訊</a>；擷取 {formatResearchDateTime(provenance.captured_at)}。本地原件與數值一致；歷史當時可得（PIT）未支援。</p>
      {data?.attribution && <p className="small-note">資料提供：{data.attribution.owner.data_provider} · {data.attribution.owner.attribution_year} · <a href={data.attribution.owner.license_url} target="_blank" rel="noreferrer">政府資料開放授權條款</a></p>}
      <details className="technical-details"><summary>查看法人原件日期、來源版本與雜湊</summary>
        <div className="table-wrap"><table><caption>來源稽核原值（{unitKnown ? '股' : '單位待核實'}）</caption><thead><tr><th>法人</th><th>買進</th><th>賣出</th><th>淨買賣超</th></tr></thead><tbody>
          {(['foreign', 'trust', 'dealer'] as const).map((key) => <tr key={key}><th>{row.investors[key].label}</th><td>{original(row.investors[key].buy, true)}</td><td>{original(row.investors[key].sell, true)}</td><td>{original(row.investors[key].net)}</td></tr>)}
          <tr><th colSpan={3}>三類法人淨買賣超合計</th><td>{original(row.total_net)}</td></tr>
        </tbody></table></div>
        <div className="overview-provenance">原始資料日 {row.source_date} · 原件列序 {row.row_ordinal} · {data?.version}</div>
        <div className="overview-provenance">來源版本 {provenance.source_version} · registry {provenance.registry_version} · manifest {provenance.manifest_digest}</div>
        <div className="overview-provenance">原件 SHA-256 {provenance.body_sha256} · 擷取紀錄 SHA-256 {provenance.receipt_sha256}</div>
        <div className="overview-provenance">擷取時間原值 {provenance.captured_at}</div>
      </details>
    </> : <div className="data-gap">尚無可核對的單日法人原件。</div>}
    <Reasons reasons={data?.reasons ?? ['daily_capture_not_configured']} />
    <p className="small-note">{windowsPresent ? '此單日區塊只核對設定原件；5／20 日窗口請見上方各窗的交易日與缺日狀態。' : '最近 5／20 交易日法人窗口仍不可用；缺少交易日基準與多日原件。'}缺值不作 0，融資不併入三大法人。</p>
  </section>
}

export function formatWindowShares(value: unknown, horizon: 1 | 5 | 20 = 1): string | null {
  return formatCanonicalShares(value, horizon)
}

function knownWindowLots(data: InstitutionalWindowsData, horizon: 5 | 20): string[] | null {
  const window = data.windows?.[String(horizon)]
  if (!window || window.horizon !== horizon || !data.horizons.includes(horizon)
    || data.unit !== 'shares' || data.quantity_encoding !== 'canonical_integer_string'
    || typeof data.as_of !== 'string' || data.supported_scope?.supported_cutoffs.includes(data.as_of) !== true
    || data.calendar?.status !== 'available' || window.status !== 'available'
    || window.required_dates.length !== horizon || window.valid_dates.length !== horizon
    || new Set(window.required_dates).size !== horizon || window.missing_dates.length !== 0 || window.invalid_dates.length !== 0
    || window.from !== window.required_dates[0] || window.to !== data.as_of || window.required_dates[horizon - 1] !== data.as_of
    || !window.required_dates.every((day, index) => day === window.valid_dates[index] && day <= data.as_of! && (index === 0 || day > window.required_dates[index - 1]))) return null
  const values = (['foreign', 'trust', 'dealer'] as const).map((key) => formatCanonicalShareLots(window.values?.[key], horizon))
  return values.every((value) => value !== null) ? values as string[] : null
}

export function InstitutionalWindows({ data, onCapture, busy = false, requestFailure }: {
  data: InstitutionalWindowsData; onCapture?: () => void; busy?: boolean; requestFailure?: string
}) {
  const state = data.capture_state
  const unitKnown = data.unit === 'shares' && data.quantity_encoding === 'canonical_integer_string'
  const cutoffSupported = typeof data.as_of === 'string' && data.supported_scope?.supported_cutoffs?.includes(data.as_of) === true
  const sourceWindow = data.windows?.['20'] ?? data.windows?.['5']
  const evidence = cutoffSupported ? (sourceWindow?.daily_evidence ?? []).filter(({ row }) =>
    row.date <= data.as_of! && sourceWindow?.required_dates.includes(row.date)) : []
  return <section className="panel overview-institutional-windows"><h3>外資／投信／自營商</h3>
    {!data.version ? <><div className="badge">資料不足</div><p>最近 5／20 交易日淨買賣超與趨勢尚不可用。</p></> : <>
      <p className="small-note">各法人淨買賣超，單位：{unitKnown ? '張' : '來源單位待核實'}；正值為買超，負值為賣超。截止包含當日，缺日不補零或改取更早日期。</p>
      {cutoffSupported && state?.can_capture && onCapture && <button type="button" className="secondary-button" disabled={busy || state.busy} onClick={onCapture}>{busy || state.busy ? '正在載入法人窗口…' : state.attempted ? '讀取本次法人窗口' : '載入5／20日法人窗口'}</button>}
      {requestFailure && <div className="data-gap" role="alert">{overviewReason(requestFailure)}</div>}
      <div className="table-wrap"><table><caption>最近 5／20 交易日法人淨買賣超（{unitKnown ? '張' : '單位待核實'}）</caption><thead><tr><th>窗口／日期</th><th>外資（不含外資自營商）</th><th>投信</th><th>自營商</th><th>交易日完整性</th></tr></thead><tbody>{([5, 20] as const).map((horizon) => {
        const window = data.windows?.[String(horizon)]
        const formatted = knownWindowLots(data, horizon)
        return <tr key={horizon}><th>{horizon} 交易日{window?.from && <div className="small-note">{formatResearchDate(window.from)} — {formatResearchDate(window.to ?? null)}</div>}</th>{formatted ? formatted.map((value, index) => <td className="numeric-cell" key={index}>{value}</td>) : <td colSpan={3}><div className="data-gap">資料不足{window?.values && '：數值或窗口條件待核對'}</div></td>}<td>{window ? `所需 ${window.required_dates.length}／已驗 ${window.valid_dates.length}／缺 ${window.missing_dates.length} 日` : '尚未核對'}</td></tr>
      })}</tbody></table></div>
      {Object.values(data.windows ?? {}).map((window) => window.missing_dates.length > 0 && <details className="technical-details" key={window.horizon}><summary>{window.horizon} 日窗口缺日與未採用原因</summary><div>缺日：{window.missing_dates.join('、')}</div>{window.invalid_dates.map((item) => <div key={item.date}>{item.date}：{overviewReason(item.reason)}</div>)}<Reasons reasons={window.reasons} /></details>)}
      <p className="small-note">來源：證券櫃檯買賣中心（TPEx） · <a href="https://data.gov.tw/dataset/11856" target="_blank" rel="noreferrer">上櫃股票三大法人買賣明細資訊</a> · <a href="https://data.gov.tw/dataset/11391" target="_blank" rel="noreferrer">櫃買指數歷史資料</a>；授權 <a href="https://data.gov.tw/license" target="_blank" rel="noreferrer">政府資料開放授權條款第 1 版（OGL 1.0）</a>。</p>
      <p className="small-note">本次取得版本的資料日期統計，只留在伺服器記憶體；讀取沿用同一批原件。取得批次涵蓋 {data.supported_scope?.supported_cutoffs.length ?? 0} 個支持截止，各窗口只採用截至所選日期的原件。發布、首次可得與修訂時間均未知，不代表歷史當時可得（PIT 未支援），不推論研究條件成立。</p>
      <details className="technical-details"><summary>查看法人窗口的每日數值、交易日與來源版本</summary>
        <div className="table-wrap"><table><caption>窗口來源稽核原值（{unitKnown ? '股' : '單位待核實'}）</caption><thead><tr><th>窗口</th><th>外資</th><th>投信</th><th>自營商</th></tr></thead><tbody>{([5, 20] as const).map((horizon) => <tr key={horizon}><th>{horizon} 交易日</th>{(['foreign', 'trust', 'dealer'] as const).map((key) => <td key={key}>{knownWindowLots(data, horizon) ? formatWindowShares(data.windows?.[String(horizon)]?.values?.[key], horizon) : '待核對'}</td>)}</tr>)}</tbody></table></div>
        <div>本次截止 {formatResearchDate(data.as_of ?? null)}；支持範圍：上櫃 3105、6488，截止 {data.supported_scope?.supported_cutoffs?.map((day) => formatResearchDate(day)).join('、') ?? '未核對'}。</div>
        <div>總覽法人版本 {data.version} · 計算版本 {data.calculation_version ?? '未核對'}</div>
        <div className="overview-provenance">來源政策版本 {data.policy?.version ?? '未核對'} · 雜湊 {data.policy?.digest ?? '未核對'}</div>
        <div>交易日基準 {data.calendar?.version ?? '未核對'}；所需 {data.calendar?.expected_dates?.length ?? 0}／已驗 {data.calendar?.valid_dates?.length ?? 0} 日。只支持 {formatResearchDate(data.supported_scope?.calendar_from ?? null)} — {formatResearchDate(data.supported_scope?.calendar_to ?? null)}。</div>
        {data.calendar?.basis && <p>週一至週五：<a href={data.calendar.basis.weekday_rule} target="_blank" rel="noreferrer">官方交易時間規則</a>；明示休市日 {data.calendar.basis.closed_dates.join('、')}：<a href={data.calendar.basis.closed_notice} target="_blank" rel="noreferrer">官方休市公告</a>。其餘預期日期均以唯一指數原件核對，不以缺列推定休市。</p>}
        {(data.calendar?.evidence ?? []).map((receipt) => <div className="overview-provenance" key={receipt.requested_date}>日曆原件 {receipt.requested_date} · <a href={receipt.url} target="_blank" rel="noreferrer">來源 CSV</a> · {receipt.source_version} · SHA-256 {receipt.body_sha256} · UTC 取得 {receipt.captured_at}{receipt.validation_scope === 'all_returned_month_rows' && <span> · 完整月原件已驗 {receipt.candidate_count} 列／本範圍採用 {receipt.adopted_count} 列／界線前已驗但未採用 {receipt.pre_calendar_row_count} 列；不推論完整月交易日曆。</span>}</div>)}
        {evidence.map(({ row, provenance }) => <details key={row.date}><summary>{row.date} · {row.company_name}（{row.symbol}） · 原件列序 {row.row_ordinal}</summary><div className="table-wrap"><table><caption>每日來源稽核原值（{unitKnown ? '股' : '單位待核實'}）</caption><thead><tr><th>法人</th><th>買進</th><th>賣出</th><th>淨買賣超</th></tr></thead><tbody>{(['foreign', 'trust', 'dealer'] as const).map((key) => <tr key={key}><th>{row.investors[key].label}</th><td>{unitKnown ? formatCanonicalShares(row.investors[key].buy, 1, true) ?? '待核對' : '單位待核實'}</td><td>{unitKnown ? formatCanonicalShares(row.investors[key].sell, 1, true) ?? '待核對' : '單位待核實'}</td><td>{unitKnown ? formatWindowShares(row.investors[key].net) ?? '待核對' : '單位待核實'}</td></tr>)}</tbody></table></div><div className="overview-provenance">原始資料日 {row.source_date} · <a href={provenance.url} target="_blank" rel="noreferrer">來源 CSV</a> · {provenance.source_version} · SHA-256 {provenance.body_sha256} · 擷取紀錄 SHA-256 {provenance.receipt_sha256} · UTC 取得 {provenance.captured_at}</div></details>)}
        <p>官方統計按當日原始成交，非錯帳／更正帳號調整後資料；下載版本是否修訂未知。本次原件 SHA-256 識別取得版本。</p>
      </details>
    </>}
    <Reasons reasons={data.reasons} />
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

function PriceMemory({ data, instrument, cutoff, explicitCutoff, onCapture, busy, failure }: {
  data: StockOverviewData['price_memory']; instrument?: Instrument; cutoff: string | null; explicitCutoff?: string
  onCapture?: () => void; busy?: boolean; failure?: string
}) {
  if (!data || !instrument || instrument.exchange !== 'TPEx' || !Object.prototype.hasOwnProperty.call(PRICE_SYMBOL_NAMES, instrument.symbol)) return null
  const known = (!explicitCutoff || explicitCutoff === cutoff) && validStockPriceMemoryRead(data, instrument, explicitCutoff || cutoff)
  const ready = priceMemoryInstrumentSupported(instrument) && priceSourcePins(explicitCutoff ?? null) !== null && memoryPriceCaptureReady(data, instrument.exchange, instrument.symbol, cutoff)
  const bar = known ? data.latest : null
  const scope = known || ready ? data.supported_scope : null
  return <section className="panel overview-price-memory" aria-labelledby="price-memory-title">
    <h3 id="price-memory-title">櫃買官方單日行情</h3>
    <p className="small-note">{scope ? <>本次政策支持的上櫃普通股：{scope.symbols.join('、')}，來源日 {scope.cutoff}。</> : <>支持範圍待核實。</>}請先明示套用截止日期，再載入行情。每次服務只取得一份指定日期原件，未提供歷史窗口。</p>
    <button type="button" className="secondary-button" onClick={onCapture} disabled={!ready || busy || !onCapture}>{busy ? '載入官方行情中…' : `載入 ${explicitCutoff ?? '指定日期'} 官方行情`}</button>
    {known ? <>
      <div className="stock-quote-grid"><div><span>收盤（元／股）</span><strong>{number(bar!.close)}</strong></div><div><span>成交量（張）</span><strong>{formatTableVolume(bar!.volume, bar!.source, bar!.volume_exact)}</strong></div><div><span>成交額（新臺幣元）</span><strong>{bar!.turnover_exact === null ? '未提供' : formatCanonicalShares(bar!.turnover_exact, 1, true)}</strong></div></div>
      <div className="overview-ohlc"><span>開 {number(bar!.open)}</span><span>高 {number(bar!.high)}</span><span>低 {number(bar!.low)}</span><span>收 {number(bar!.close)}</span></div>
      <p className="small-note">資料日 {formatResearchDate(bar!.date)} · <a href={bar!.provenance.endpoint} target="_blank" rel="noreferrer">櫃買中心 · 上櫃股票行情（11370）</a>；本次暫存，重啟後需重新載入。擷取時間不是發布時間，歷史當時可得未支援。</p>
      <p className="small-note">{data.attribution!.owners.join('、')} · {data.attribution!.year} · {data.attribution!.release_version} · <a href={data.attribution!.license_url} target="_blank" rel="noreferrer">政府資料開放授權條款 OGL 1.0</a>。</p>
      <details className="technical-details"><summary>查看官方價格原列、來源版本與 SHA</summary>
        <div className="overview-provenance">單一原件：全 {data.provenance!.row_count} 列已核結構；金融數值僅核 {data.provenance!.selected_symbols.join('、')}。CSV 資料列序 {bar!.row_ordinal}；記憶體 ID {data.provenance!.memory_capture_id}。</div>
        <div className="table-wrap"><table><caption>官方 CSV 原字串：價格為元／股，成交股數為股，成交金額為新臺幣元；空白成交額表示未提供。</caption><thead><tr><th>欄位</th><th>來源原值</th></tr></thead><tbody>{PRICE_HEADERS.map((field) => <tr key={field}><th>{field}</th><td>{bar!.source_fields[field]}</td></tr>)}</tbody></table></div>
        <div className="overview-provenance">原件 SHA-256 {data.provenance!.body_sha256}</div><div className="overview-provenance">擷取紀錄 SHA-256 {data.provenance!.receipt_sha256}</div>
        <div className="overview-provenance">政策 {data.provenance!.policy_version} · {data.provenance!.policy_digest}</div>
        <div>請求開始 UTC {data.provenance!.request_started_at} · 完成 UTC {data.provenance!.captured_at}</div>
        <div>raw_payload_id null · ingestion_run_id null · bar id null；沒有建立 DB 記錄。發布／首次可得／修訂時間未知。</div>
      </details>
    </> : <div className="data-gap">{data.status === 'available' ? '記憶體行情契約待核實，未採用數值。' : '此截止尚無已核對的官方單日行情。'} 不以其他日期行情補值。</div>}
    {!known && <Reasons reasons={data.reasons} />}
    {failure && <><p role="status">官方行情載入未完成；請核對來源詳情。此批次不自動重試。</p><details className="technical-details"><summary>查看載入原因</summary>{overviewReason(failure)}（{failure}）</details></>}
    <p className="small-note">此資料只含一天，趨勢與研究條件仍待補；載入失敗後不自動重試。</p>
  </section>
}


export function StockOverview({ data, instrument, explicitCutoff, onCapturePrice, capturingPrice, priceRequestFailure, onNews, onCaptureEvents, capturingEvents, eventRequestFailure, onCaptureWindows, capturingWindows, windowRequestFailure }: {
  data: StockOverviewData; onNews: () => void; onCaptureEvents?: () => void; capturingEvents?: boolean; eventRequestFailure?: string
  onCaptureWindows?: () => void; capturingWindows?: boolean; windowRequestFailure?: string
  instrument?: Instrument; explicitCutoff?: string; onCapturePrice?: () => void; capturingPrice?: boolean; priceRequestFailure?: string
}) {
  const price = data.price
  const latest = price.latest
  const memoryKnown = instrument && (!explicitCutoff || explicitCutoff === data.as_of) ? validStockPriceMemoryRead(data.price_memory, instrument, explicitCutoff || data.as_of) : false
  return <section className="stock-overview" aria-labelledby="stock-overview-title">
    <div className="section-head overview-head"><div><div className="eyebrow">研究總覽</div><h2 id="stock-overview-title">資料截止 {formatResearchDate(data.as_of)}</h2></div><span className="badge">{memoryKnown || latest ? '價格來源已核對／部分資料待補' : '研究資料待補'}</span></div>
    <p className="overview-cutoff-note">依資料日期截至的事後研究；不代表歷史當時可得。價格保留原始口徑，尚未提供完整還原鏈。</p>
    <div className="overview-grid">
      <PriceMemory data={data.price_memory} instrument={instrument} cutoff={data.as_of} explicitCutoff={explicitCutoff} onCapture={onCapturePrice} busy={capturingPrice} failure={priceRequestFailure} />
      {!memoryKnown && <section className="panel overview-price"><h3>既有價格與實際視窗</h3>
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
      </section>}
      <InstitutionalWindows data={data.institutional} onCapture={onCaptureWindows} busy={capturingWindows} requestFailure={windowRequestFailure} />
      <InstitutionalDaily data={data.institutional_daily} windowsPresent={Boolean(data.institutional.version)} />
      <section className="panel overview-conditions"><h3>研究條件</h3>{data.conditions.map((condition) => <div className="overview-condition" key={condition.strategy}><div className="position-head"><strong>{condition.label}</strong><span className="badge">{condition.status === 'met' ? '成立' : condition.status === 'not_met' ? '未成立' : '資料不足'}</span></div><p className="small-note">既有結果日期 {formatResearchDate(condition.signal_date)}</p><Reasons reasons={condition.reasons} /><details className="technical-details"><summary>查看策略版本</summary>{condition.strategy} · 版本 {condition.version ?? '尚無可核對結果'}</details></div>)}<p className="small-note">沿用既有固定規則；輸入需求不等於條件成立，仍需補齊資料後才能形成完整交易計畫。</p></section>
      <OfficialEvents data={data.events} onCapture={onCaptureEvents} busy={capturingEvents} requestFailure={eventRequestFailure} />
      <section className="panel"><h3>新聞與公告入口</h3><p>保留既有來源連結、發布與事件時間。</p><button type="button" className="secondary-button" onClick={onNews}>查看新聞與公告</button><p className="small-note">新聞採已核對的發布／事件時間截至；未知時間或超過截止的項目不混入本次清單。</p></section>
    </div>
    <details className="technical-details"><summary>研究範圍與總覽版本</summary>總覽版本 {data.version}。法人窗口依上方各窗狀態，支持範圍及截止見法人區塊；價格、設定的單日法人原件及明示取得的除權息預告沿各自證據；其他範圍與研究條件尚未完成。歷史當時可得（PIT）未支援。</details>
  </section>
}
