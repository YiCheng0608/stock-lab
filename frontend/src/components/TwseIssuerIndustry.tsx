import type { OfficialEventsData, TwseIssuerIndustryData, TwseIssuerProfileData } from '../types'
import { validTwseIssuerIndustry } from '../twseIssuerIndustry'

export function TwseIssuerIndustry({ data, issuer, events, exchange, symbol, cutoff, requestFailure }: {
  data: TwseIssuerIndustryData; issuer?: TwseIssuerProfileData; events: OfficialEventsData
  exchange: string; symbol: string; cutoff: string | null; requestFailure?: string
}) {
  const valid = validTwseIssuerIndustry(data, exchange, symbol, cutoff, issuer, events)
  const row = valid && !requestFailure && data.status === 'available' ? data.row : null
  const trace = row ? data.provenance : null
  const declaration = trace?.taxonomy_citation.declaration
  return <section className="panel overview-issuer-industry"><h3>產業名稱與碼表追溯</h3>
    <p className="small-note">臺灣證券交易所兩條完整碼名引用。以本次公司原碼查對名稱，來源與日期分別保留。</p>
    {!row && <div className="data-gap" role="alert">{requestFailure || !valid ? '本次產業名稱讀取或來源核對失敗，已清除名稱與追溯。' : '尚無同截止公司原碼、事件與碼名引用可共同核對的資料。'}</div>}
    {row && trace && declaration && <>
      <div className="table-wrap"><table><caption>本次 TWSE 公司原碼與完整產業名稱</caption><tbody>
        <tr><th>公司原始產業碼</th><td>{row.industry_code_raw}</td></tr><tr><th>TWSE 碼表名稱</th><td>{row.name_zh}</td></tr>
        <tr><th>公司分類生效日</th><td>未知</td></tr>
      </tbody></table></div>
      <p className="small-note">資料來源：臺灣證券交易所 · {declaration.sources.map((source, i) => <span key={String(source.source_id)}>{i > 0 && ' · '}<a href={String(source.url)} target="_blank" rel="noreferrer">{i === 0 ? 'B.12.00 附錄三' : i === 1 ? '2023 產業格式公告' : '產業分類規則第2條'}</a></span>)}。</p>
      <p className="small-note">基表2018年10月修訂、2020年3月實施（月精度）；公告2023-05-30、變更2023-07-03生效；規則2025-06-09修訂。以上均非本公司分類生效日。</p>
      <details className="technical-details"><summary>查看產業名稱版本與來源追溯</summary>
        <div className="overview-provenance">引用版本 {declaration.version} · 官方文件觀測日 {data.metadata_observed_date}</div>
        <div className="overview-provenance">原公司列序 {row.issuer_row_ordinal} · 事件列序 {row.event_row_ordinals.join('、')}</div>
        <div className="overview-provenance">公司來源 {trace.issuer.source_version} · 事件來源 {trace.event.source_version}</div>
        <div className="overview-provenance">公司原件 SHA-256 {trace.issuer.body_sha256} · 擷取紀錄 SHA-256 {trace.issuer.receipt_sha256}</div>
        <div className="overview-provenance">事件原件 SHA-256 {trace.event.body_sha256} · 擷取紀錄 SHA-256 {trace.event.receipt_sha256}</div>
        <div className="overview-provenance">引用宣告 SHA-256 {trace.taxonomy_citation.canonical_root_attested_excerpt_sha256} · registry {trace.taxonomy_citation.registry_version} · {trace.taxonomy_citation.content_digest}</div>
        <p className="small-note">碼名引用來自已核對的官方文件解析內容，引用宣告雜湊不是 PDF、公告或規則原件的雜湊；沒有原始文件擷取紀錄。</p>
      </details>
    </>}
    <p className="small-note">僅供兩條完整碼名的本地研究引用；不代表完整現行分類、普通股或 ETF 身分、族群成員、可信排名或歷史當時可得。</p>
  </section>
}
