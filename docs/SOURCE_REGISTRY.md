# Source registry、用途 gate 與官方來源契約

本文負責官方來源 identity、授權、用途 gate、capture 與 consumer 契約。各節有限 review 不代表其餘來源已重新查證、全市場 coverage 或 PIT。

本文件是免費公開官方來源的 identity、授權、用途 decision、runtime capture 與已接 consumer 的權威。第 3 節是原 snapshot 四來源，第 8 節是另需 explicit 單來源 manifest 的 TPEx 單日法人，第 13 節是獨立版本的政府連結 CSV policy；不能將新增來源當成 bundled default 或沿用舊 registry version。一次 HTTP 200、來源名稱或資料日期都不能補成完整 coverage、發布時間、first availability、revision lineage 或 historical PIT。

## 現行節次索引

各版本 policy、pins 與 capture 彼此獨立；新 explicit 版本不提升舊 default、不沿用舊 capture bytes，也不作 implicit latest。已歸檔節次與子節不在本文，查 Git 指標；`git show f431b9885cd3332ddd328309d0041a15c55b8610:docs/SOURCE_REGISTRY.md` 取得歸檔前全文，下表連結為該版本的行範圍。

| 節 | 範圍 | 現況與歸檔指標 |
| --- | --- | --- |
| [§1](#1-registry-與-policy-契約) | Registry 與 policy 契約（顯式 manifest、registry_version 與 canonical digest 的 pin 判定） | 現行 |
| [§2](#2-官方共同證據與限制) | 官方共同證據與限制 | 現行 |
| [§3](#3-四個准入來源) | 原 snapshot 四個准入來源 | 現行 |
| [§4](#4-standalone-source-capture) | Standalone source capture 執行入口 | 現行 |
| [§5](#5-兩個-capture-consumers) | 兩個 capture consumers：`STOCK_DAY_ALL` selected bars（5.1）、`holidaySchedule` 正面排除（5.2） | 現行 |
| [§6](#6-tpextwse-有限資料品質契約) | TPEx／TWSE 有限資料品質契約 | 現行 |
| [§7](#7-review-receipt-與未完成範圍) | 原 snapshot Registry pin 與 review 範圍 | 現行；7.1～7.3 為 review 證據 |
| [§8](#8-m1-p2atpex-日法人來源與-selected-摘要) | M1-P2a：TPEx 日法人來源與 selected 摘要 | 現行 |
| [§9](#9-m1-p3atwt48u-selected-官方事件原件摘要) | M1-P3a：TWT48U selected 官方事件原件摘要 | 現行 |
| [§10](#10-m1-後續依賴審查來源候選與等待邊界) | M1 後續依賴審查：來源候選與等待邊界 | 現行 |
| [§11](#11-m2-p1本次官方事件-feed-摘要) | M2-P1：本次官方事件 feed 摘要 | 現行 |
| [§12](#12-m1-p4atwse-單日法人有界審查與准入缺口) | M1-P4a：TWSE 單日法人有界審查與准入缺口 | 現行 |
| [§13](#13-m1-w1tpex-多日法人與完整有界交易日) | W 系列共同基礎：政府連結 CSV 來源與用途（13.1）、完整有界日曆規則（13.2）、原件／整數／缺日契約（13.3） | 現行（保留 §13.1～13.3）；移出內容見原節：[L351–L398](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/SOURCE_REGISTRY.md#L351-L398) |
| §14～§18 | M1-W3～W7 三至七截止法人來源與窗口 | 歸檔：[L400–L716](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/SOURCE_REGISTRY.md#L400-L716)；現行見 [§19](#19-m1-w8八截止法人來源與完整有界日曆) |
| [§19](#19-m1-w8八截止法人來源與完整有界日曆) | M1-W8：八截止（2026-09-21～10-02）法人來源、27 日曆與 96 net 參考；worker `tpex-institutional-window/w8-v1` | 現行；§19.4 只保留 96 net 參考表，移出內容見原節：[L718–L793](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/SOURCE_REGISTRY.md#L718-L793) |
| [§20](#20-m1-price-1tpex-兩股單日價格來源與准入) | M1-PRICE-1：TPEx 兩股單日價格來源與准入（20.1 資源、用途與 10/05 policy；20.2 10/05 金融值；20.7 10/06 policy 與金融值） | 現行（保留 20.1、20.2 金融值表、20.7）；移出內容見原節：[L795–L869](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/SOURCE_REGISTRY.md#L795-L869) |
| §21 | M2-FOCUS-STOCK-SCOPE-1 三股來源准入 | 歸檔：[L871–L903](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/SOURCE_REGISTRY.md#L871-L903)；policy `.1` 見 [§29.1](#291-1006-價格-policy-tuple-版本表) |
| §22 | M1-CLOSE-RESOURCE-1 有界單日 JSON 觀測 | 歸檔：[L905–L915](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/SOURCE_REGISTRY.md#L905-L915)；無現行用途准入 |
| §23 | M2-FOCUS-STOCK-SCOPE-2 四股來源准入 | 歸檔：[L917–L945](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/SOURCE_REGISTRY.md#L917-L945)；policy `.2` 見 [§29.1](#291-1006-價格-policy-tuple-版本表) |
| §24 | M1-HISTORY-QUERY-1 官方月查詢線索與准入缺口 | 歸檔：[L947–L955](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/SOURCE_REGISTRY.md#L947-L955)；歷史月資源未准入，摘要見 [DATA_SOURCES](DATA_SOURCES.md) |
| §25 | M2-FOCUS-STOCK-SCOPE-3 五股來源准入 | 歸檔：[L957–L989](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/SOURCE_REGISTRY.md#L957-L989)；policy `.3` 見 [§29.1](#291-1006-價格-policy-tuple-版本表) |
| §26 | M1-HISTORY-MONTH-WIRE-1 月參數推論與用途缺口 | 歸檔：[L991–L1014](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/SOURCE_REGISTRY.md#L991-L1014)；歷史月資源未准入，摘要見 [DATA_SOURCES](DATA_SOURCES.md) |
| §27 | M2-FOCUS-STOCK-SCOPE-4 六股來源准入 | 歸檔：[L1016–L1046](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/SOURCE_REGISTRY.md#L1016-L1046)；policy `.4` 見 [§29.1](#291-1006-價格-policy-tuple-版本表) |
| §28 | M1-HISTORY-OPEN-DATA-LINK-1 開放平台 metadata 與歷史用途缺口 | 歸檔：[L1048–L1074](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/SOURCE_REGISTRY.md#L1048-L1074)；歷史月資源未准入，摘要見 [DATA_SOURCES](DATA_SOURCES.md) |
| [§29](#29-m2-focus-stock-scope-5七股來源准入) | M2-FOCUS-STOCK-SCOPE-5：七股（default 2026-10-06）policy `.5` 與 10/06 價格 policy tuple 版本表（`.1`～`.5`） | 現行；29.1 版本表為新整理（資料取自原 §21／§23／§25／§27／§29），原節：[L1076–L1104](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/SOURCE_REGISTRY.md#L1076-L1104) |
| [§30](#30-m1-price-save-1私人單日保存與跨程序讀回) | M1-PRICE-SAVE-1：私人單日保存 storage policy、三檔 schema 與跨程序重驗 | 現行（保留 §30.1、§30.2）；移出內容見原節：[L1106–L1136](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/SOURCE_REGISTRY.md#L1106-L1136) |
| [§31](#31-m1-chips-cutoff-1006-1同1006法人窗口與完整有界日曆) | M1-CHIPS-CUTOFF-1006-1：explicit 10/06 法人窗口、24 日曆與 12 net 真值 | 現行（保留 §31.1～31.4 真值表）；移出內容見原節：[L1138–L1186](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/SOURCE_REGISTRY.md#L1138-L1186) |
| [§32](#32-m1-saved-price-focus-1006-1保存來源的七股關注准入) | M1-SAVED-PRICE-FOCUS-1006-1：保存來源的七股關注用途與精確篩選、七股金融真值 | 現行（保留 §32.1、§32.2、§32.3 讀取上限）；移出內容見原節：[L1188–L1232](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/SOURCE_REGISTRY.md#L1188-L1232) |
| [§33](#33-m1-saved-price-chips-integration-1006-1保存行情與法人窗口共同入口) | M1-SAVED-PRICE-CHIPS-INTEGRATION-1006-1：保存行情與法人窗口共同入口、五份 policy、私人三檔 hash | 現行（保留 §33.1、§33.2、§33.3 的 gate 與 mask 規則）；移出內容見原節：[L1234–L1279](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/SOURCE_REGISTRY.md#L1234-L1279) |
| [§34](#34-m1-saved-price-chips-focus-1006-1保存行情與法人條件關注准入及日曆缺口) | M1-SAVED-PRICE-CHIPS-FOCUS-1006-1：保存行情與法人條件關注的新用途與八條件精確篩選契約 | 現行（保留 §34.1 契約）；移出內容見原節：[L1281–L1311](https://github.com/YiCheng0608/stock-lab/blob/f431b9885cd3332ddd328309d0041a15c55b8610/docs/SOURCE_REGISTRY.md#L1281-L1311) |
| [§35](#35-m2-focus-stock-scope-6八股與新來源日准入) | M2-FOCUS-STOCK-SCOPE-6：八股與新來源日准入 | 現行 |
| [§36](#36-m1-saved-price-chips-focus-calendar-1006-2全月日曆與八條件來源准入) | M1-SAVED-PRICE-CHIPS-FOCUS-CALENDAR-1006-2：全月日曆與八條件來源准入 | 現行 |
| [§37](#37-m1-saved-price-chips-focus-stock-scope-7-1006-1七股共同來源准入) | M1-SAVED-PRICE-CHIPS-FOCUS-STOCK-SCOPE-7-1006-1：七股共同來源准入 | 現行 |
| [§38](#38-m1-chips-stock-scope-7-daily-net-trend-20-1006-1七股每日法人淨超與窗口累計) | M1-CHIPS-STOCK-SCOPE-7-DAILY-NET-TREND-20-1006-1：七股每日法人淨超與窗口累計 | 現行 |
| [§39](#39-2026-10-08歷史收盤新候選審查與官方事件重選) | 歷史收盤新候選審查與官方事件重選（39.1 M2-OFFICIAL-EVENT-DATE-RANGE-20261008-1 實際來源結果） | 現行 |
| [§40](#40-m2-official-event-kind-20261008-1b1事件類型實際來源與有限接受) | M2-OFFICIAL-EVENT-KIND-20261008-1/B1：事件類型實際來源 | 現行 |
| [§41](#41-m1-twse-issuer-event-profile-20261008-1b1真-issuer-與同截止事件有限接受) | M1-TWSE-ISSUER-EVENT-PROFILE-20261008-1/B1：真 issuer 與同截止事件 | 現行 |
| [§42](#42-m1-twse-issuer-industry-trace-20261008-1b1兩碼引用與同截止原件) | M1-TWSE-ISSUER-INDUSTRY-TRACE-20261008-1/B1：兩碼引用與同截止原件 | 現行 |
| [§43](#43-m1-chips-stock-scope-7-gross-trade-20-1006-1b1七股gross買賣與新來源准入) | M1-CHIPS-STOCK-SCOPE-7-GROSS-TRADE-20-1006-1/B1：七股 gross 買賣與新來源准入 | 現行 |
| [§44](#44-m1-chips-stock-scope-7-direction-segments-20-1006-20261008-1b1七股方向計數與窗口區段) | M1-CHIPS-STOCK-SCOPE-7-DIRECTION-SEGMENTS-20-1006-20261008-1/B1：七股方向、計數與窗口區段 | 現行 |
| [§45](#45-m1-chips-stock-scope-7-adjacent-windows-5-1006-20261008-1b1兩相鄰5日比較與新來源准入) | M1-CHIPS-STOCK-SCOPE-7-ADJACENT-WINDOWS-5-1006-20261008-1/B1：兩相鄰 5 日比較與新來源准入 | 現行 |
| [§46](#46-m1-chips-stock-scope-7-dealer-components-5-1006-20261008-1b1自行買賣避險與合計來源及對帳) | M1-CHIPS-STOCK-SCOPE-7-DEALER-COMPONENTS-5-1006-20261008-1/B1：自行買賣、避險與合計來源及對帳 | 現行 |
| [§47](#47-36-qa1qa2七股-tpex-法人六日-dated-csv-與兩截止五日分子issue36-two-cutoffs-v1) | #36 qa1／qa2：七股 TPEx 法人六日 dated CSV 與兩截止五日分子（`issue36-two-cutoffs-v1`） | 現行 |
| [§48](#48-31-qa1qa2qa3七股-finmind-融資餘額與兩截止五日變動比ordinary-margin-cutoffs-1005-1006-v2) | #31 qa1／qa2／qa3：七股 FinMind 融資餘額與兩截止五日變動比（`ordinary-margin-cutoffs-1005-1006-v2`） | 現行 |

## 1. Registry 與 policy 契約

CLI 與 policy decision 必須顯式指定 manifest。Library `load_manifest()` 只讀 bundled fixed snapshot；它不是 implicit latest，也不構成 external pin。只有外部同時 pin `registry_version` 與 canonical digest 才是 `pinned`；只有 version 是 `version_only_unverified`，兩者皆無是 `unverified`。

Manifest 保存 `schema_version`、`registry_version`、`policy_version`；每個 source row 另存相同 schema／registry version 與自己的 `source_version`，且至少包含：

| 類別 | 必要內容 |
| --- | --- |
| identity | `source_id`、dataset identity/type、營運者／提供機關、exact endpoint/method、endpoint/schema version。 |
| evidence/access | 官方 Swagger、資料集、授權與網站條款 URL及 `checked_at`；公開／驗證、免費、授權版本、顯名、完整性與限制。 |
| operation/time | 更新頻率、發布／延遲、rate limit、retry/429、資料日期、first available、歷史範圍、revision/withdrawal/supersedes、PIT 可重建性。未知須存 `unknown + reason`。 |
| retention/lifecycle | `raw_store`／`summarize` 分開的權利與 metadata；`enabled`、catalog 狀態、deprecation/notice、一般停止條款。 |
| purpose policy | `local_fetch`、`raw_store`、`summarize`、`historical_pit` 各自的事實、理由、證據與限制。 |

三層狀態不可混用：

- Evidence：`known`、`unknown`、`explicitly_prohibited`。官方未說明是 unknown。
- Purpose policy：`admitted`、`denied`、`unknown`。一種用途的正面證據不能讓另一用途自動通過。
- Public decision：`allow`、`restricted`、`unsupported`，並帶 machine-readable `reasons` 與 `conditions`。

`allow` 只表示該 source/purpose/profile 的 policy eligibility；runtime 必須另證 conditions 已履行。必要 evidence 未知、`enabled` 非 known true、endpoint/method mismatch、pin/digest conflict 均 fail closed。非該用途必要的 rate limit 或 deprecation unknown 只保留限制，不能反向封鎖其他已有正面證據的用途；`historical_pit` unsupported 也不封鎖 fetch/store/summarize。

`source-policy/v1` validator 固定最小 evidence 與 condition 集：`local_fetch` 要求 `free_public=true`、`auth=false`、documented terms；`raw_store`／`summarize` 各要求自己的 retention evidence；所有用途要求 `enabled=true`。Manifest 不得刪減集合繞過 gate。

測試樣本重用：真實資料進[唯讀樣本庫](development-baseline/README.md#測試資料庫分層)前，須依保存形式取得該 source 的 `raw_store` 或 `summarize` admitted，並記 `source_id`、`source_version`、`policy_version`。重用只限本機開發與 QA，不公開散布或上 GitHub；權利 unknown／denied 不收錄，取得當時的配額與 NO-RETRY 不因樣本重用而重置。

## 2. 官方共同證據與限制

- [TWSE Swagger](https://openapi.twse.com.tw/v1/swagger.json) 是 Swagger 2.0，HTTPS、`host=openapi.twse.com.tw`、`basePath=/v1`、info version `1.0`。
- [TPEx Swagger](https://www.tpex.org.tw/openapi/swagger.json) 是 OAS 3.0，server `https://www.tpex.org.tw/openapi/v1`、info version `1.0.0`。
- 四個政府資料集均標示免費與[政府資料開放授權條款第 1 版](https://data.gov.tw/license)。Raw 保存與摘要須顯名、保留來源完整性與 traceability；授權不等於 endpoint SLA。
- [TWSE 使用條款](https://www.twse.com.tw/zh/terms/use.html)限制未經同意的自動下載；准入只採官方 OpenAPI 明示介接，不外推到任意爬蟲或無上限批次。[TPEx 條款](https://www.tpex.org.tw/zh-tw/gtsm_disclaimer.html?l=zh-tw)要求引用標示來源並維持完整性。

四條 path 的 authentication/security scheme、數字 rate limit、精確發布時鐘、revision history 與 endpoint-specific deprecation notice均未由 Swagger 證實。一次無驗證 200 只代表當次公開可讀。

## 3. 四個准入來源

本節只描述原 snapshot 四來源；第 8 節新增來源使用另 explicit 單來源 manifest，不列入本組 default／version／pins。

| `source_id` | Exact endpoint／method | 官方資料集／版本 | 更新與時間限制 |
| --- | --- | --- | --- |
| `twse_stock_day_all` | `GET https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL` | [dataset 11549](https://data.gov.tw/dataset/11549)；TWSE `1.0` | 每日；endpoint 無參數，可取範圍、精確發布、first availability、revision及 rate limit unknown。 |
| `twse_holiday_schedule` | `GET https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule` | [dataset 11761](https://data.gov.tw/dataset/11761)；TWSE `1.0` | 年度最新版本；通常 12 月前提供次年度不是 exact availability。歷年 archive、修訂、撤回 unknown。 |
| `twse_twt48u_all` | `GET https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL` | [dataset 89748](https://data.gov.tw/dataset/89748)；TWSE `1.0` | 不定期；payload 可含未來預告，須保存 capture time。完整歷史與 revision unknown。 |
| `tpex_spendi_history` | `GET https://www.tpex.org.tw/openapi/v1/tpex_spendi_history` | [dataset 48665](https://data.gov.tw/dataset/48665)；TPEx `1.0.0` | 不定期；名稱含「歷史」不代表逐次發布版本、完整 archive 或 PIT lineage。 |

營運者為 TWSE／TPEx，資料集提供機關為金融監督管理委員會證券期貨局。四筆均為免費、OGL 1.0、公開 OpenAPI 且未列 auth；raw／summary 僅在顯名、完整性、取得時間、hash、license／version 與 traceability 條件下使用。資料集上架或 metadata 更新日不是 record first availability 或 payload revision time。

`free_public_local` decision matrix：

| `source_id` | `local_fetch` | `raw_store` | `summarize` | `historical_pit` |
| --- | --- | --- | --- | --- |
| `twse_stock_day_all` | `allow`; `bounded_requests,respect_endpoint_limits` | `allow`; `attribute_source,preserve_source_integrity` | `allow`; 前述加 `retain_traceability` | `unsupported`; 缺 first availability、reconstructable snapshot、revision history |
| `twse_holiday_schedule` | `allow`; 同上 | `allow`; snapshot 不冒充歷史全集 | `allow`; 同上 | `unsupported`; 逐版 availability/revision 未證 |
| `twse_twt48u_all` | `allow`; 同上 | `allow`; 必存 capture time | `allow`; 同上 | `unsupported`; 預告 availability、更正與撤回史未知 |
| `tpex_spendi_history` | `allow`; 同上 | `allow`; 同上 | `allow`; 同上 | `unsupported`; 沒有逐次 snapshot/revision availability |

## 4. Standalone source capture

已 review executor 是 `python -m worker.source_runtime capture`；完整參數與 PowerShell 範例見 [操作手冊 §4](OPERATIONS.md#4-source-registry-與-capture)。

Library `capture(...)` 接受相同 selectors，只有 local test 可注入 transport。每次須顯式給 manifest、profile、source、兩個 external pins 與 output directory；不能由 URL 反推 source，也不會改變 legacy collect／daily／backfill。Runtime allowlist 包含第 3 節原 snapshot 四組 `source_id + exact URL + GET`，及第 8 節另 explicit 單來源 manifest 的 TPEx 日法人 exact GET；manifest 新列不會自動可執行。

任何 request/file action 前必須驗 manifest/profile/source version/endpoint/method，並取得 `local_fetch` 與 `raw_store` 的 allow decisions。每個 condition 必須有已知 handler；未知／不支援 condition 或無法履行的 numeric limit 在零 request 時 fail closed。

| Condition | 可觀測契約 |
| --- | --- |
| `bounded_requests` | Exact endpoint 單一 GET，零 retry/redirect/warm-up；body 上限 5 MiB。HTTP 15 秒是 per-operation timeout；30 秒只在 streamed chunks 間 cooperative check，不是 hard total deadline。 |
| `respect_endpoint_limits` | `trust_env=false`；非 2xx 停止；429/503 `Retry-After` 原值進 failure receipt。目前 numeric rate limit unknown，故 `rate_limit_verified=false`；不宣稱跨執行／process 節流。 |
| `attribute_source` | `receipt.json.attribution` 保存 owner/dataset/source/URL/terms/evidence與兩種 purpose evidence；頂層保存 manifest/source pins及 exact endpoint/method。 |
| `preserve_source_integrity` | 送 `Accept-Encoding: identity`；拒絕非 identity `Content-Encoding`。`body.bin` 是 transfer framing 後、content decoding 前 bytes；strict JSON validation 不改寫 body，SHA-256 與 byte count對應相同 bytes。 |

Output 必須是專案外、具名且已授權的新目錄或空目錄，不得寫正式／`.local` DB或覆寫既有 capture。唯一成功 artifact 是 ZIP_STORED `capture.zip`，成員順序 exact `body.bin`、`receipt.json`。`receipt.json` schema 是 `source-capture/v1`，包含 aware UTC `request_started_at/captured_at`、status、body hash/bytes、HTTP status、pins、policy/condition receipts、rate-limit evidence與 attribution。Bundle 先在 staging 完成，再以 exclusive hard link 發布；衝突或不支援 hard link即 fail closed，且不留下本程式擁有的 half bundle。

失敗只由 library return 或 CLI stdout 輸出 receipt：`status` 是 `rejected`（零 request）或 `capture_failed`，含 `error_reason`，移除 `artifact` 並令 `executed_purposes=[]`；CLI exit 2，不另寫 failed artifact。

這條 capture path 只執行所選 allowlisted 來源的 `local_fetch + raw_store`；不解析 source truth、不接 legacy collector，也不執行 summarize、historical PIT、排程、worker／product persistence 或全來源 gate。第 8 節的另行唯讀摘要 consumer 不等於 capture executor 執行 summarize。

## 5. 兩個 capture consumers

### 5.1 `STOCK_DAY_ALL` selected-security bars

Library flow：

~~~text
load_stock_day_capture(capture_zip, manifest=..., profile=...,
  expected_registry_version=..., expected_digest=...,
  expected_market_date=..., output_dir=...)
→ TwseAdapter(stock_day_capture=capture)
→ OfficialMarketDataAdapter
→ 既有 collect(..., force=True)
~~~

沒有 CLI。Loader 重驗 ZIP_STORED exact members、bytes/hash、receipt schema/status、source/endpoint/GET、external pins/source version、fetch/store decisions/conditions與 aware UTC capture time，才在 caller 指定的專案外 output 以 lock + exclusive `xb` materialize `body.bin`/`receipt.json`。每次 `select(...)` 再驗 materialized bytes與 metadata。雙 plain files不是原子出版或永久 immutable store；unsigned local metadata不是 authenticity proof。

全 body 先驗為非空 JSON object array；每列 `Code` nonblank且全域唯一，所有 `Date` 可解析、同日且等於 expected market date。選中 symbols 的 OHLC 必須完整、finite、positive；`TradeVolume` 是非負 signed-64-bit exact integer，且 `high >= max(open,close)`、`low <= min(open,close)`、`high >= low`。數字以 Decimal 解析；選中 symbol 或 OHLC／volume 缺失、無效仍回具 symbol 的 stable unavailable reason。`TradeValue` 明確非負數（含 `0`）標 `available`；缺失或無效時保留有效 OHLC／volume，`turnover=0` 另標 `unavailable/missing` 或 `unavailable/invalid`，不得把數值零當有效來源零。未選列不產生 OHLCV 或全市場 coverage 聲明。保存與舊資料處置見 [資料來源：P2+](DATA_SOURCES.md#r1-a2-p2-成交金額可得狀態有限接受)。

Capture 對 matching date 的 selected TWSE security row具權威性：同日 `MI_INDEX` 不可補 capture missing/invalid symbol；其他歷史日期仍走 legacy MI_INDEX。合法列保存原 hash、capture time 與 materialized refs；`RawPayload.collected_at` 用 capture UTC，`MarketBar.collected_at` 是 ingestion-now。Raw reuse key 是 `ingestion_run_id + source + endpoint + sha256`。`adj_close = record.adj_close or record.close` 仍不是 adjustment truth。

選中 symbol／OHLC／volume 缺失或無效仍可使 run partial；成交額 unavailable 可附 warning。upsert-only 不刪舊 bar。此來源沒有 TAIEX，不能單獨證交易 session；同日 MI_INDEX/TAIEX 須獨立成立。Matching date之外的 feed仍走原 adapter/fetcher，故不是完整 offline gate。純列 helper 有記憶體驗證；另已有限驗收單一離線落盤 fixture 的缺額／明確零經 selected capture→SQLite→API 路徑。指定三種 invalid／四類拒收另有有限磁碟驗收；未覆蓋的 invalid／拒收、真官方與逐欄 coverage 仍待驗，範圍見 [P2+ 資料契約](DATA_SOURCES.md#r1-a2-p2-成交金額可得狀態有限接受)。

### 5.2 `holidaySchedule` positive exclusion

Library flow 是 `load_holiday_capture(...) → TwseAdapter(holiday_capture=...)`。Loader 接受 manifest/profile/external pins、`expected_schedule_year` 與 external output；驗證與 materialization邏輯同上。它只在 `fetch_bars(start,end)` 多日分支替代 holiday GET，讓核定 closed weekday不送 `MI_INDEX`；單日 range不使用。顯式 capture失敗不 fallback，成功 request key需 `force=True` 才消費。

全 body 是非空 object array；每列 exact `Name`、`Date`、`Weekday`、`Description` 都須為 string。日期只接受契約列出的 ROC/Gregorian compact、slash、hyphen格式，須無歧義、全 body unique、同屬 expected year；中文 weekday須一致。Range可跨年，但只排除 capture年度內 explicit closed dates；其他年度正常查詢。

Closed grammar只接受有限 holiday-name allowlist、exact `依規定放假1日。`、日期／weekday／日數可重算一致的多日放假／補假完整句，以及 exact `市場無交易，僅辦理結算交割作業` + empty Description；除受控 `<br>`／空白 normalization外不做 substring推論。開始交易、春節前最後交易及 unknown wording都不構成 open/closed truth。

Calendar只控制本次 request，不寫 `OfficialBatch.no_data_dates`、不新增／刪除 bar/TAIEX/session，也不修既有 closed-date資料。若本流程可見的有效 daily OHLC或 current index落在 explicit closed date，fail closed；未抓取 MI_INDEX不宣稱已檢查。Schedule date是 content，capture time是本系統觀測；published/first-available/revision/archive/PIT仍未證。

## 6. TPEx/TWSE 有限資料品質契約

### 6.1 TPEx today halt/action 語意

`tpex_spendi_today` 不是第五個 registry source或 capture consumer。它的 exact fields `Date`、`SecuritiesCompanyCode`、`CompanyName`、`暫停交易`、`恢復交易` 同時容納暫停與恢復公告，因此「代號存在」不是當日仍停牌 truth。Collector仍保存 raw；非空公告只留既有純文字 warning，不新增 machine reason。空列也不證開市；`force=False` reuse不會回修舊 flag/evaluation。

時間角色必須分離：row `Date` 是來源資料日；`DateOfSuspendedTrading`／`DateOfResumedTrading` 是事件生效／排程日；collector `end/data_as_of` 是研究 cutoff；raw `collected_at`／receipt `captured_at` 是本系統觀測時間。它們都不是 official publication或逐列 first availability。Future resume可是在 cutoff前已公告，不能一律刪除，但沒有受驗 availability就不能作 historical PIT。

### 6.2 TPEx history identity 與 split-row linkage

`Serial` 是「編號」，永遠不能作 symbol。`parse_tpex_suspension_history_rows(...)` 的 identity順序固定為 `SecuritiesCompanyCode` → `Code` → `證券代號` → `代號`；後三者只是 local aliases。`_text` 取第一個 trim後 nonblank，再做 exact `allowed_symbols` membership；較前欄 nonblank但不在 universe時不 fallback。Alias conflict/type policy仍未實作；raw `source_row` 可保留 Serial。

Split-row linkage只在同一 selected symbol全部輸入恰為兩列時成立：一列只有可解析 start、另一列只有可解析 resume，且 `start < resume`；invalid/empty/duplicate列也計入兩列上限。成功時 suspension details保留 start `source_row`，新增 `resumed_date`、`interval_end`、完整 `resumption_source_row`；resumption event保持原樣。

其他形狀均沿用 row-local behavior：malformed、倒置、same-day/intraday、同列雙日期、multiple cycles或 identity ambiguity不新增拒絕/reason；row-local 輸出 `interval_end=null` 時，legacy 消費此列仍有無界延長的缺陷。Upsert可更新同 key但不刪舊錯 event，不重算既存 evaluation；完整 history capture、PIT與 repair未完成。

### 6.3 TPEx corporate action mapping

- `stock_dividend_ratio`：只從 exact `StockDivdendThousandShares` 或 local `每仟股無償配股` 取 first nonblank，`parse_number` 成功後除以 1,000。不得用 `StockDividend`、`權值`、`無償配股率`。
- `reference_price`：只讀 exact `ClosePriceBeforeExRightsDiviend` 或 local `除權息前收盤價`。不得用 `OpeningReferencePrice`／`開始交易基準價`。
- `cash_dividend` precedence：`CashDivdend` → `CashDividend` → `現金股利` → `息值`。只在 missing/null/empty/whitespace時看下一欄；第一個 nonblank只 parse一次，非法值不降級。

現行無 paid subscription時 factor為 `1/(1+Rf) × (P-C)/P`，對應官方 `Q/P`；官方一般公式是 `Q=(P-C+S×Rp)/(1+Rf+Rp)`。現行沒有可信 paid ratio `Rp` 與 subscription price `S`，所以 paid subscription unsupported。Previous-bar reference fallback不是 official pre-close truth；generic numeric hardening、舊資料 repair/replay也未完成。

### 6.4 TWSE `source_action_classification`

`GET /instruments/{symbol}` 的 `corporate_actions[]` 有 read-only分類：

| Field | Contract |
| --- | --- |
| `kind` | `ex_dividend`、`ex_right`、`ex_right_and_dividend`、`unknown` |
| `label` | `除息`、`除權`、`除權息`、`未知` |
| `raw` | Exact `{"field":"Exdividend","value":...}`；原值為 string才原樣保留，否則 null。 |
| `reason` | 固定 precedence：`unsupported_source` → `invalid_details` → `missing_official_field` → `alias_conflict` → `identity_mismatch` → `unknown_raw_value` → `trusted_twse_exact_fields` |

只有 action source exact `twse`、instrument exchange exact `TWSE`、nonempty Mapping details，及 exact `Code/Date/Exdividend` 都為 nonblank string才分類。Code trim等於 symbol；Date須是 valid 7-digit ASCII ROC date且等於 action date；Exdividend只接受 exact `息/權/權息`。Local aliases `股票代號/證券代號/除權息日期/除權息` 只驗一致，不得補 canonical missing；非 string或語意衝突 fail closed。

Classification不證 raw membership/hash/FK、authenticity、official event ID、availability、revision、完整性或 PIT，也不改 type、DB identity、factor、raw、worker或前端。既有同日 multi-type duplicate factor風險仍未修。

## 7. Review receipt 與未完成範圍

原 snapshot 四來源 Registry pin：`registry_version=r1-a1-c009-2026-09-12.1`；canonical `content_digest=sha256:eb6c290d7716300c4117bb2cdc61a66cbf8d62e344870928933b44b77461f87b`。這是已 review manifest identity；runtime仍須由 caller顯式提供兩個值。第 8 節單來源 manifest 必須使用自己的 version／digest，不能沿用本組 pins。

### 7.1 Round18 C018 standalone source capture final review 證據

有限 review 涵蓋四個 allowlisted endpoint 的 capture shape、condition receipts、exclusive publish 與失敗不發布。該輪 live 只涵蓋 `STOCK_DAY_ALL`；其餘當時只有 mock／介面驗證，因此不能外推 live transport、來源內容或 coverage。

### 7.2 Round19 C019-B `STOCK_DAY_ALL` content／consumer final review 證據

有限 review 涵蓋完整 body validation、selected Decimal OHLCV、matching-date 權威性、raw／capture time 與缺值 partial 邊界；不構成全市場、session 或 PIT 證據。

### 7.3 Round20 C020-B `holidaySchedule` content／consumer final review 證據

有限 review 包含一次 `holidaySchedule` live capture，以及 exact fields／year／date／weekday、窄 closed grammar、多日 positive exclusion、source conflict 與不修舊資料邊界；不構成完整 calendar、open-session 或 PIT 證據。逐輪命令、case count、hash 與 probe 明細留在 Git 歷史。

仍未完成：

- 原四來源已有 `STOCK_DAY_ALL` 與 `holidaySchedule` 兩個有限磁碟 ZIP capture consumers；第 9 節另為 TWT48U selected 事件新增已有限 review 的記憶體 consumer，不支持既有 ZIP 讀入。TWT48U selected／feed 的有限產品接線由[個股頁 §11–13](STOCK_RESEARCH_PAGE.md#11-m1-p3bselected-官方事件總覽接線)負責；Event／News 持久化、`tpex_spendi_history` capture 接線與完整 legacy collector gate 仍缺。
- `historical_pit` 需逐筆 first-available、revision/withdrawal lineage及可重建 snapshots；event/date/current raw不能替代。
- `tpex_spendi_today` 不在四來源 manifest；完整 halt/action/session/TAIEX truth、C007 store linkage、B5b/PIT與正式資料分類仍未完成。
- Paid subscription、TWSE/TPEx action identity/duplicate修正、generic numeric hardening、舊資料 repair與既有 evaluation replay仍需獨立設計及授權。

## 8. M1-P2a：TPEx 日法人來源與 selected 摘要

M1-P2a 是解除 M1 的 TPEx 日法人 source gate 的必要基礎批次，來源准入、capture／selected 摘要及下述具名驗收已有限 review。只採 exact `GET https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading`，另以 explicit [`tpex_institutional_registry.json`](../backend/worker/tpex_institutional_registry.json) 單來源 manifest 執行；原第 3 節 snapshot、bundled default 與其 pins 不變。此准入不放行 legacy `dailyTrade` 或 TWSE `T86`；後續單日總覽接線另依[個股頁 §10](STOCK_RESEARCH_PAGE.md#10-m1-p2b單日法人原件總覽接線)，不由 P2a 來源准入直接宣稱產品完成。

單來源 pins 為 `registry_version=m1-p2a-tpex-institutional-2026-10-03.1`、`content_digest=sha256:7ca17724e029c6a417dd2baa1981e6396d74772e977aecd1e823fde0e0090146`；`source_id=tpex_3insti_daily_trading`、`source_version=tpex-3insti-daily-trading-oas3-info1.0.0-2026-10-03`。Source version 是本地查證 snapshot 名稱，不能當成官方保留的 revision 或歷史版本鏈。

### 8.1 官方證據與用途邊界

統籌於 **2026-10-03** 核對：

- [政府資料集 11856](https://data.gov.tw/dataset/11856) 記載免費、每日更新與政府資料開放授權條款第 1 版，並連到 TPEx OpenAPI。
- [TPEx Swagger](https://www.tpex.org.tw/openapi/swagger.json) 是 OAS 3.0、info version `1.0.0`、server `https://www.tpex.org.tw/openapi/v1`；exact GET path `/tpex_3insti_daily_trading` 的名稱為「上櫃股票三大法人買賣明細資訊」，未列 parameters／security，info 明示歡迎介接。這是 exact OpenAPI 介接證據，不外推任意網站自動下載。
- [TPEx 網站條款](https://www.tpex.org.tw/zh-tw/gtsm_disclaimer.html?l=zh-tw) 第 5 點限定經同意方式自動下載，第 7 點對政府資料開放平臺資料依開放授權使用；引用仍須標明來源並維持完整性。[OGL 1.0](https://data.gov.tw/license) 第 2 點允許重製、編輯與改作免另行授權，第 3 點要求顯名。

`free_public_local` 的 `local_fetch`、`raw_store`、`summarize` 取得有限准入，仍須分別履行 bounded request／endpoint limit、顯名、原件完整性、版本／hash／時間與 traceability 條件。`historical_pit` 為 `unsupported`；精確發布時鐘、逐筆 first availability、完整歷史、revision／withdrawal lineage、數字配額與 endpoint-specific deprecation 皆未知。每日更新與來源 `Date` 不代表可重建交易日曆或歷史當時可得版本。

TWSE `T86` 保持用途准入證據 `unknown`：本次 [TWSE Swagger](https://openapi.twse.com.tw/v1/swagger.json) 未找到該 path，亦未取得對應 exact dataset／介接同意；[TWSE 使用條款](https://www.twse.com.tw/zh/terms/use.html) 第 6 點的自動下載限制不能由 legacy endpoint 可讀而略過。此結論不稱 TWSE 明文禁止 `T86`，也不由 TPEx 的正面證據放行 TWSE。

### 8.2 Selected 摘要契約與操作

[`tpex_institutional_capture.py`](../backend/worker/tpex_institutional_capture.py) 提供 `summarize_capture(...)` 與 `summarize_capture_bytes(...)`，輸出版本為 `tpex-institutional-selected/v1`。Consumer 只讀既有 `capture.zip`，在記憶體驗證，不解壓、改寫原件、寫 DB 或送網路 request；每次需 explicit manifest／profile、兩個外部 pins、Gregorian expected date 與非空、無重複 selected symbols。

以**股**（`unit=shares`）為單位，分開輸出**外資及陸資（不含外資自營商）**、**投信**與**自營商**的 buy／sell／net。只接受 canonical ASCII 整數字串：buy／sell 非負，net 可帶正負，範圍為正負 `9223372036854775807`；空白、逗號、單位、小數、科學記號、前導零與 `-0` 均拒收。各類須滿足 `net = buy - sell`，`TotalDifference` 必須等於三類 net 合計；外資自營商不得再加一次。合法來源零保留零，缺值、無效或不一致不補零；任一 requested selected 不合格即整份摘要 unavailable，CLI exit 2 並給具體 reason，成功 exit 0。

全 body 為非空 JSON object array；每列 `Date` 僅接受七碼民國 `ROC_YYYMMDD` 且須等於 caller 的 expected date，security code 非空，requested selected 各須恰有一列。只驗 selected 的公司名、三組數量與合計，不將其他列的數量稱為已核對；duplicate JSON key 或非有限數值仍拒收。外資 total-sell 的 exact source key 含**前導空白**，不自行改欄名；每個 buy／sell／net 的 `source_fields` 隨摘要保存。

Consumer 重驗 ZIP_STORED exact `body.bin`／`receipt.json` 成員、大小及 body hash、successful receipt、source／endpoint／GET／版本／pins、型別敏感的 policy／condition／attribution 內容及 aware、順序一致的 request／capture time；檔案讀取前後重驗 identity／bytes，拒絕 symlink、hardlink 或途中變更。摘要保存 body／receipt 雙 hash、原件 1-based row ordinal、capture time、來源與版本、attribution、summarize decision 及 condition receipts。`provenance.verification=local_evidence_consistent` 只證本地原件／receipt 一致，不是官方 origin authentication。

`candidate_count` 是全 body 列數，`selected_count` 是本次合格選列數，`as_of` 是顯式 expected data date；`session_windows.status=unavailable`，保留 `trading_session_source_not_admitted` 與 `multi_session_institutional_evidence_missing`。Selected `status=available` 不代表 5／20 交易日窗口 available。

在 repo 的 `backend` 目錄、已可執行 worker 的 Python 環境中，改入**既有且核定** `capture.zip` 路徑後可執行下例；日期與 symbols 必須對應原件，結果只輸出 stdout。取得新原件仍用第 4 節 runtime `capture`，顯式指定本節 manifest、source、pins 與核定的新 output 目錄。

~~~powershell
$env:PYTHONUTF8 = '1'
$taskManifest = Join-Path (Get-Location) 'worker\tpex_institutional_registry.json'
$taskCaptureZip = 'C:\authorized-capture\capture.zip' # 改成既有原件的絕對路徑
python -m worker.tpex_institutional_capture summarize `
  --capture-zip $taskCaptureZip `
  --manifest $taskManifest `
  --profile free_public_local `
  --expected-registry-version m1-p2a-tpex-institutional-2026-10-03.1 `
  --expected-digest sha256:7ca17724e029c6a417dd2baa1981e6396d74772e977aecd1e823fde0e0090146 `
  --expected-date 2026-10-02 `
  --symbol 3105 --symbol 6488
~~~

### 8.3 有限核對與尚缺項

統籌已有限接受 **2026-10-03 單次 exact runtime capture**：1 GET、HTTP 200，來源資料日 **2026-10-02**，原件 **910 列**日期一致；**TPEx 3105／6488** 各三組 buy／sell／net 加 total、共 **20 個數值**逐欄與原件一致。Consumer CLI subprocess exit 0，讀前後 ZIP hash 不變；舊四來源 manifest bytes 與 HEAD 一致。同一真實 ZIP 的錯日期 `2026-10-01`、缺 selected `9999`、全零 expected digest 各為 unavailable／CLI exit 2，reason 分別為 `payload_date_mismatch`、`selected_row_missing`、`content_digest does not match expected pin`，不回傳 rows，讀前後 ZIP hash 不變。

本批程式、具名正負向操作及必要記憶體回歸已有限接受；完整 backend 未跑。原失敗／修正、命令、exit 及版本收據留 task，不增加多日、交易 session 或產品完成度。

M1-P2a 本身不接 DB、legacy collector、總覽 API／UI 或多日彙總；完整 5／20 交易日的市場基準、缺日與窗口 coverage 仍待核定及驗收。單日列數、官方資料日或單次真實摘要均不能補成完整交易日曆、全市場／歷史 coverage 或 PIT。工作狀態見 [M1 接線映射](ROADMAP_EXECUTION.md#21-近期里程碑接線映射)。

後續 M1-P2b 沿用本節固定來源、用途與原件 gate，唯讀 server 明示的 ZIP／日期，把單日 selected 接到總覽 API／UI，不新增來源准入或改 default manifest。兩檔真實原件的二十個 API 數值、原件／receipt 追溯與具名 UI 操作已有限 review；精確支持範圍與產品契約由[個股頁 §10](STOCK_RESEARCH_PAGE.md#10-m1-p2b單日法人原件總覽接線)負責，不增加完整 session、全市場／歷史 coverage 或 PIT 完成度。

## 9. M1-P3a：TWT48U selected 官方事件原件摘要

M1-P3a 是支援 M1、解除 selected 官方事件原件 consumer 缺口的必要基礎批次，**程式及下述具名驗收已有限 review**。只採原四來源 snapshot 的 `twse_twt48u_all` 與 exact `GET https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL`；產品總覽接線留 M1-P3b。本節不修改原 registry、policy、source version 或 pins，也不新增 DB／legacy collector 接線。

### 9.1 本輪官方補證與既有 identity

統籌於 **2026-10-03** 唯讀核對 [政府資料集 89748](https://data.gov.tw/dataset/89748)：免費、政府資料開放授權條款第 1 版、不定期更新，並連到 TWSE OpenAPI。[TWSE Swagger](https://openapi.twse.com.tw/v1/swagger.json) 的 info version 為 `1.0`、description 明示歡迎介接；exact GET `/exchangeReport/TWT48U_ALL` 的 `Date` 定義為「除權息日期」，`Code`、`Name`、`Exdividend` 等十二個欄位均為 string。這些證據只支持該 exact OpenAPI 介接，不外推任意網站自動下載。[TWSE 使用條款](https://www.twse.com.tw/zh/terms/use.html) 第 6／8 點與 [OGL 1.0](https://data.gov.tw/license) 的自動下載、顯名與完整性條件仍依原契約。

執行沿用 [`source_registry.json`](../backend/worker/source_registry.json) 的 `registry_version=r1-a1-c009-2026-09-12.1`、`content_digest=sha256:eb6c290d7716300c4117bb2cdc61a66cbf8d62e344870928933b44b77461f87b` 與 `source_version=twse-twt48u-all-d011-2026-09-12`。本輪補證不把這個本地 snapshot 名稱改成新的官方 revision；發布／首次可得時間、完整歷史、更正／撤回版本鏈、數字 rate limit 及 historical PIT 仍未知。其餘原三來源未於本輪重新查證。

### 9.2 記憶體 capture 與 selected 摘要契約

[`source_runtime.py`](../backend/worker/source_runtime.py) 新增 `capture_memory(...)`，回傳 `(body bytes 或 None, receipt bytes)`。這條獨立路徑使用 `source-memory-capture/v1`、`storage=memory_only`，不含頂層 `artifact`、不建立 ZIP 或任何原件檔案；既有第 4 節 `source-capture/v1` 磁碟路徑不改。仍核對 explicit manifest／profile／source／雙 pins，履行 `local_fetch`／`raw_store` 的用途與條件；成功 receipt 記錄此兩個 executed purposes，但不表示已作磁碟持久化。單一 GET、body 上限 5 MiB、零 retry／redirect／warm-up、identity encoding 與第 4 節時間限制不變，30 秒 cooperative check 不稱 hard total deadline。失敗回 `body=None`，receipt 為 `rejected` 或 `capture_failed`、`executed_purposes=[]`，不產生失敗附件。

[`twse_action_capture.py`](../backend/worker/twse_action_capture.py) 提供 `summarize_memory_capture(...)` 與 `live_summarize(...)`，輸出 `twse-action-selected/v1`。Selected symbols 必須是非空、無重複的 4–6 碼 ASCII 大寫字母或數字，原值 exact matching；`live_summarize` 於 GET 前先驗 symbols 與 fetch／store／summarize 三個用途。CLI 須 explicit source selector；memory capture 的固定 allowlist 只支持本節來源，不擴張其他來源用途。

Consumer 重驗成功 memory receipt 的 source／endpoint／GET／versions／雙 pins、body bytes／SHA-256、型別敏感的 policy／condition／attribution、HTTP 2xx、`request_count=1` 與 aware、順序一致的 UTC request／capture 時間；頂層不得帶 disk artifact。全 body 必須為非空 JSON object array，各列 exact `Code` 合格、`Date` 是有效七碼 ASCII 民國日期，duplicate JSON keys／非有限值拒收。只對 selected 驗 `Name` 為 nonblank string、`Exdividend` exact `息/權/權息`，分別輸出除息／除權／除權息；不以 alias 補 canonical 欄位，也不推測 alias 語意。每個 requested symbol 至少有一個合格事件；selected 相同 `Code + Date + Exdividend` 重複即拒收，其餘多事件保留。Missing selected 是 unavailable，不代表已驗證該股沒有事件；任一 selected 不合格即不回成功 rows。

摘要保留 exact `source_row`、1-based 原件列序、body／receipt 雙 hash、request／capture UTC、來源／授權／版本及 summarize condition receipts。`candidate_count` 是全 body 列數，`selected_count` 是本次合格**事件列數**，不一定等於 symbols 數；輸出依 requested symbols 順序分組，各股保留原件列序。`validation_scope=payload_codes_dates_and_selected_identity_classification` 明列全 body code／date 與 selected identity／classification 的驗證範圍，不聲稱其他欄位或全市場事件 completeness。`source_url_kind=feed` 表示來源入口是資料集，不是本則單篇原文。`provenance.verification=local_evidence_consistent` 只證本地 bytes／receipt 一致，不是官方 origin authentication。

來源 `Date` 轉成 `event_date`，角色為 `effective_date`、精度為 `date`，原字串另留 `source_date`。`published_at`、`first_available_at`、`revision_available_at` 均為 null／unknown；capture time 只是本系統本次觀測。未來除權息預告保留，不作歷史 `as_of` 篩選，也不推論價格影響或產生調整因子。時間語意由[新聞與事件規格](NEWS_SPEC.md#9-m1-p3a官方事件原件摘要的時間邊界)負責。

在 repo 的 `backend` 目錄、已可執行 worker 的 Python 環境中，可用以下命令作**單次 live GET**。原件只留記憶體、摘要只輸出 stdout；成功 exit 0，失敗 unavailable／exit 2，不建立檔案。Symbols 需對應當次原件，範例不能保證之後版本仍有相同事件。

~~~powershell
$env:PYTHONUTF8 = '1'
$taskManifest = Join-Path (Get-Location) 'worker\source_registry.json'
python -B -m worker.twse_action_capture live-summarize `
  --manifest $taskManifest `
  --profile free_public_local `
  --source twse_twt48u_all `
  --expected-registry-version r1-a1-c009-2026-09-12.1 `
  --expected-digest sha256:eb6c290d7716300c4117bb2cdc61a66cbf8d62e344870928933b44b77461f87b `
  --symbol 0056 --symbol 1449 --symbol 1463
~~~

### 9.3 驗收與保留邊界

統籌於 **2026-10-03（台北）** 已有限接受程式、記憶體回歸與 source gate 縮窄後必要靶向複驗，以及兩次成功 live：一個 `capture_memory → consumer` 直接核原 body，另一個由實際 CLI parser → capture → consumer → stdout；當次 body **58 列**，每次獨立單一 GET、HTTP 200、無 retry／原件落盤。以下三筆 exact selected 欄位、完整 `source_row`、原件列序及追溯欄位已核對；0056 是 ETF，不能稱三檔普通股票。

| Code／Name | 原 Date → 生效日期 | 原 Exdividend／分類 | 原件列序 |
| --- | --- | --- | --- |
| `0056`／元大高股息（ETF） | `1151022` → 2026-10-22 | `息`／除息 | 5 |
| `1449`／佳和 | `1151012` → 2026-10-12 | `權`／除權 | 49 |
| `1463`／強盛新 | `1151015` → 2026-10-15 | `息`／除息 | 50 |

三筆均為本次觀測到的**未來生效預告**，不證當時 availability 或價格影響。另一次 live CLI 因原件缺 selected 6834 回 unavailable／exit 2；未改報成功，web 較舊內容不代替 network 原件。P3a 無前端變更、不新增 API／UI 驗收；完整 backend／磁碟出版未驗，原收據留 task。

此 memory consumer 不支持既有 ZIP 讀入，P3a 本身不接 API／UI／DB，`durable_capture=false`、`historical_pit=unsupported`；完整歷史、事件群組／修訂與產品研究條件仍未完成。後續 M1-P3b 的 selected 總覽接線已有限 review，精確支持範圍見[個股頁 §11](STOCK_RESEARCH_PAGE.md#11-m1-p3bselected-官方事件總覽接線)，不由產品接線擴張本節來源與時間邊界。

Live body／receipt 未保存，**不能離線重播這次原件**；再取得的內容／版本可能不同，Git fixture 只重建邊界測試。命令、分類、hash 及收據留原 task；後續產品支持由[個股頁 §11](STOCK_RESEARCH_PAGE.md#11-m1-p3bselected-官方事件總覽接線)負責。

## 10. M1 後續依賴審查：來源候選與等待邊界

統籌已接受 **2026-10-03** 的 M1 後續依賴唯讀審查，未改程式、manifest／pins 或用途 decision，不增加能力完成度。現行 TPEx exact 日法人 resource 未列參數，`historical_coverage` 仍 unknown；第 8 節 consumer 要求全 body 日期等於單一 `expected_date`，server 為單 ZIP／日期配置。既有核定原件只支持 **2026-10-02、910 列**的單日驗收，沒有多日原件或完整窗口證據。

[政府資料集 11391](https://data.gov.tw/dataset/11391) 的官方名稱為「櫃買指數歷史資料」，描述為提供當日收盤後的上櫃大盤指數資訊，標示免費、每日更新與 OGL 1.0；名稱與 metadata 未證明提供完整多日原件或交易日基準。[日法人資料集 11856](https://data.gov.tw/dataset/11856) 仍是每日資料，第 8 節准入不外推歷史用途。本次官方 schema 與候選原件未成功取得，transport 結果留本輪 task；尚不能核對實際欄位、日期範圍或完整性，不推論永久不可用或禁止介接。

成交日實列最多證已觀測日，不能由缺列推休市或最近 5／20 交易日完整 coverage，因此本次不建立孤立的 observed-session 計算核心冒充依賴解除。候選服務恢復後可先作有界可行性核實，成功讀取不等於來源與窗口門檻通過；主缺口、恢復條件及新統籌流程見 [ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑)。本次未重搜 TWSE T86 或 R0-B2，其原未知／待驗邊界保留。

以上是2026-10-03原 OpenAPI 候選的有限審查，仍未放行該候選。後續 M1-W1 已由另外兩個政府連結 CSV、明示休市及完整正值指數行解除具名有界依賴，見[§13](#13-m1-w1tpex-多日法人與完整有界交易日)；兩者來源／用途與 coverage 不互相外推。

## 11. M2-P1：本次官方事件 feed 摘要

**程式及下述具名驗收已 review（有限）。** 本批只支援既有 `twse_twt48u_all`、exact GET、`free_public_local` profile 與第 9 節原 manifest／source version／雙 pins，不新增准入或修改原 snapshot。Memory capture、receipt 與各用途條件仍依第 9.2 節；[`twse_action_capture.py`](../backend/worker/twse_action_capture.py) 新增 `summarize_memory_feed(...)`，輸出 `twse-action-observed-feed/v1`、`validation_scope=all_observed_identity_dates_classification`，供官方事件關注清單使用。

與 selected 摘要分開，全 feed 摘要接受 JSON object array，包括合法空 `[]`；逐列驗 exact `Code`、nonblank `Name`、有效七碼 ASCII 民國 `Date`、exact `Exdividend=息/權/權息`，相同 `Code + Date + Exdividend` 重複拒收，不以 alias 或猜測補 canonical 欄位。任一列不合格即整份 unavailable，不挑剩餘列湊清單。Duplicate JSON keys、非有限值及不合格 receipt／pins／hash／時間仍拒收。這是全 body 身分、日期與分類的驗證，不放行未驗金融欄位、全市場 completeness 或事件歷史。

摘要保留原件列序、原值身分／日期／分類、effective-date 角色、body／receipt 雙 hash、request／capture UTC、固定版本與 attribution／purpose／condition receipts。空摘要只證本次合格原件零列，不是官方全市場「沒有事件」；不以空結果推導單股缺 selected 可用。第 9 節 selected API 的非空請求與缺 selected 拒收契約維持。

`candidate_count` 是全 body 列數，`selected_count` 是合格事件列數；全 feed 版本將全部來源代碼排序放入 `selected_symbols`，每股事件保持原件列序，與 requested-symbol selected 版本分開。合法空 `[]` 回 available、兩個 count 都是 0、`selected_symbols=[]`，仍有 receipt、雙 hash 與顯名／用途條件；之後 selected 讀同一空原件仍以 `nonempty_row_list_required` 拒收。非空 feed 的任何 invalid code／日期／名稱／分類、重複事件、非 object row 或非 list payload，分別保留 `invalid_security_code`、`invalid_effective_date`、`selected_name_missing`、`selected_event_class_unknown`、`selected_event_duplicate`、`row_object_required`、`row_list_required`；`selected_*` 在本函式指全部觀測列，不表示只檢查某幾股。

來源日期仍是生效日，capture time 只是本次觀測；published／first available／revision 仍 unknown，`historical_pit=unsupported`。Consumer 不寫 DB／檔案／ZIP，不形成調整因子、價格影響或利多分類。本次 feed 到關注清單、最多 100 股與已知 catalogue 的 M1 連結由[個股頁 §12](STOCK_RESEARCH_PAGE.md#12-m2-p1官方事件關注清單接個股總覽)負責，產品接線不擴大來源准入或時間支持範圍。

M2-P2 在完整 feed consumer 驗證後才按來源 `Code`／任一 `Name` 搜尋，符合結果再排序及套 100 股上限，匹配外或上限外的壞列不得跳過；搜尋不改原件事件列數、摘要版本或原件 bytes／pins。本批不新增來源／用途准入或歷史支持，來源正負向與產品驗收分開；精確搜尋／計數／返回契約及本次支持範圍由[個股頁 §13](STOCK_RESEARCH_PAGE.md#13-m2-p2官方事件清單搜尋與研究往返)負責。

已有限接受 **2026-10-03** 單次 exact memory GET 的 **58 列／58 代碼**：全身分、日期、分類及列序與 actual API 一致，receipt／雙 hash／pins 已核。空 feed、同股多事件、上限及拒收是另行記憶體 fixture，不作當次 live 情境或全市場證據。完整 backend 未跑；原件未保存，不能離線重播。產品具名範圍見[個股頁 §12.3](STOCK_RESEARCH_PAGE.md#123-驗收與尚缺項)，收據留 task。

## 12. M1-P4a：TWSE 單日法人有界審查與准入缺口

統籌已接受 **2026-10-03** 的有界可行性及程式唯讀審查，支援 M1 的 TWSE 單日法人來源評估；**來源未准入，等待精確證據**。本輪只核對官方頁面／metadata、用途權利及既有接線，不取得法人原件，不新增 consumer、API／UI、manifest 或 pins，不增加能力完成度。這是依賴等待，不是使用者暫停，也不表示 ROADMAP 全部餘項受阻。

### 12.1 官方證據與用途邊界

| 官方來源 | 當次核對與限制 |
| --- | --- |
| [TWSE T86 公開查詢頁](https://www.twse.com.tw/zh/trading/foreign/t86.html) | 頁面提供日期、分類及 CSV 入口，提示資訊自民國 `101-05-02` 起提供。這只證 UI 提示，未取得當次法人 body，不證完整歷史、實際欄位、單位或 selected 數值。 |
| [TWSE OpenAPI UI](https://openapi.twse.com.tw/)／[Swagger metadata](https://openapi.twse.com.tw/v1/swagger.json) | 程式以唯一一次 raw Swagger GET 檢查 **143 個 paths**，當次未見 `T86`。搜尋 `fund`／`insti`／`foreign`／`T86` 及三大法人／三法人／投信／自營商，僅找到 `MI_QFIIS_cat`、`MI_QFIIS_sort_20`；兩者為持股股數／比率，不能代替三類法人買賣流量。官方 UI 顯示 version `1.0`／OAS 2.0，不能據此補成 raw 回應的版本證據。 |
| [TWSE 使用條款](https://www.twse.com.tw/zh/terms/use.html) | 第 6 點要求自動下載依同意的方式，第 8 點另列政府開放資料例外；查詢頁可看或舊 collector 可取，均不能代替 exact 資源／方式的准入證據。 |
| [政府資料開放授權條款第 1 版](https://data.gov.tw/license) | OGL 1.0 適用已釋出的資料。本輪官方搜尋未取得 TWSE exact 個股三類買賣流量資源與授權的對應；不能由 TPEx 資料集 11856、其他已准入 OpenAPI 或網站可讀外推。 |

上述 raw Swagger 命令 exit 0；HTTP status、raw version／timestamp／hash 未記錄，保持未知，不稱 HTTP 200、完整法人 body 通過或可離線重播，也不為補 hash 再抓。命令、版本、exit 及限制的實際收據留原 task。

Exact TWSE 候選的 `local_fetch`、`raw_store`、`summarize` 權利證據仍為 `unknown`，用途未准入；本輪未建立或變更 manifest decision。欠缺正面證據不改寫成 `explicitly_prohibited`，也不宣稱 TWSE 全面禁止或永久不可用。

### 12.2 缺證與恢復條件

完整實際欄位、資料日、單位、全 body 列數／一致性與具名 selected 原值及數值均**未取、未驗**；不填猜值或以 mock 代替。恢復本批須依序滿足：

1. 取得 exact 官方 TWSE 資源／方式對免費 `local_fetch`、`raw_store`、`summarize` 的正面權利證據，以政府開放資料的 exact 對應或其他官方明示授權，證實免費及三項用途逐一成立；不跨資源移轉授權。
2. 統籌據此核定一次有界、純記憶體的完整單日 body，核實實際欄位、資料日、單位、完整回應與具名 selected；成功讀取本身不算 gate 通過。
3. 所需 gate 具體滿足後，統籌才核定另 explicit 最小來源准入、consumer 精確寫入白名單及單日 M1 總覽所需子能力；此前不變更 pins 或放行實作。接線另須原件→consumer→API 數值與追溯、同截止及具名桌面／窄版操作驗收，見 [M1 接線映射](ROADMAP_EXECUTION.md#21-近期里程碑接線映射)。

完整 5／20 交易日基準及 PIT 不作本批單日前置；本批審查也不解除多日窗口、全市場／完整歷史 coverage、研究條件或 PIT 的原門檻。

### 12.3 驗收邊界

本批只有 metadata／唯讀 source review，程式寫入範圍為空；未取法人 body，未跑 tests／backend／build／UI，不由前輪測試追認准入。入口副作用見[開發文件](development-baseline/README.md)，角色／清理限制見[治理 #1](https://github.com/YiCheng0608/stock-lab/issues/1)。

取得 §12.2 的 exact 權利與資源證據後，才由統籌核定有界驗證及必要實作。優先順序依 [ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑)，不以此來源等待暫停其他已具依賴的核心能力。

## 13. M1-W1：TPEx 多日法人與完整有界交易日

本節是 W 系列的共同基礎：§13.1 政府連結 CSV 來源與用途、§13.2 完整有界日曆規則、§13.3 原件／整數／缺日契約；[§19](#19-m1-w8八截止法人來源與完整有界日曆) 與 [§31](#31-m1-chips-cutoff-1006-1同1006法人窗口與完整有界日曆) 沿用。W1 當時的 policy 與取得上限不是現行設定，現行 policy 見 [§19.1](#191-新版policy用途與取得上限)。

W1 範圍：TPEx 3105／6488、唯一資料截止2026-10-02，日曆限2026-09-01～10-02；不計完整 M1 或 PIT。W2 同截止 API／UI 見[個股頁 §18](STOCK_RESEARCH_PAGE.md#18-m1-w2同截止法人窗口與原件追溯)。

### 13.1 獨立 policy 與四用途

[`tpex_institutional_window.py`](../backend/worker/tpex_institutional_window.py) 的 W1 當時 policy（已由 §19.1 取代）版本為 `tpex-institutional-window/w1-v1`、profile `free_public_local`。外部 pins 為 `policy_version=m1-w1-tpex-window-2026-10-04.1`、`policy_digest=sha256:5b5129cdc39ab0bac9eac89246917f8721c118e2f9c18ed02234972e6c5dc773`；型別／來源集合、四用途、整份 policy 與外部 digest 必須一致。原 registry／policy JSON、P2a manifest、bundled default 與其 pins 未改。

| Source ID／版本 | 准入的政府連結 exact GET 與觀測查詢 |
| --- | --- |
| `tpex_government_institutional_csv`；`dataset-11856-dated-csv-observed-2026-10-04/v1` | [dataset11856](https://data.gov.tw/dataset/11856) 的 [CSV](https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data)，附 `d=115/MM/DD`，僅下述20個日期。 |
| `tpex_government_index_csv`；`dataset-11391-month-csv-observed-2026-10-04/v1` | [dataset11391](https://data.gov.tw/dataset/11391) 的 [指數 CSV](https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?response=data)，附 `date=2026/09/01` 或 `2026/10/01`。 |

統籌核實這兩個政府連結資源免費、適用[政府資料開放授權條款第1版](https://data.gov.tw/license)，及[TPEx 網站條款](https://www.tpex.org.tw/zh-tw/gtsm_disclaimer.html?l=zh-tw)第7點的開放資料例外。`local_fetch`、`raw_store`、`summarize` 各為 `admitted`，須署名 Taipei Exchange (TPEx)、保留授權／政府資料集／exact URL、原件完整性、hash、版本及取得時間，並履行有界請求。`historical_pit=unsupported`；這不放行 legacy POST、其他日期、TWSE 或任意自動下載。查詢日期參數是本次實測行為，不是官方參數 SLA；數字 rate limit、精確發布／first availability、revision lineage 及停用承諾仍未知。

### 13.2 完整有界日曆與窗口

日曆版本為 `tpex-2026-09-01_2026-10-02-weekdays-11503027221/v1`。以[周一至五交易規則](https://www.tpex.org.tw/zh-tw/mainboard/trading/rules/system.html)與[2026-09-17公告11503027221](https://www.tpex.org.tw/storage/eb_data/11509/11503027221.html)明示9/25、9/28休市，建立2026-09-01～10-02的 expected dates；兩月 CSV 必須恰好包含全部22個開市日，每行 OHLC 正值、有限且界限一致。缺月、缺日、額外／重複日、休市衝突或競爭版本均使日曆及全部窗口 unavailable。不由缺列推休市，不把這段完整性外推全年或其他市場。

cutoff 必須 exact `2026-10-02`，含截止日向前取 expected session，版本為 `independent-net-sum/expected-session-inclusive-v1`：

- 5日：9/24、9/29、9/30、10/1、10/2。
- 20日：9/3、9/4、9/7、9/8、9/9、9/10、9/11、9/14、9/15、9/16、9/17、9/18、9/21、9/22、9/23、9/24、9/29、9/30、10/1、10/2。

### 13.3 原件、整數及缺日契約

Consumer 嚴格驗 UTF-8 CSV、exact 25欄法人／6欄指數 header、全列欄數及日期。法人全列驗日期等於 requested date、代碼唯一且為4～6碼 ASCII 大寫字母／數字、名稱非空；僅3105／6488的全部金融欄位作數值驗證，兩股各須恰有一列，不稱其他標的金融數值已核。

daily 股數接受 canonical ASCII 整數字串，絕對值上限 `9223372036854775807`；buy／sell 非負，每組 net 等於 buy－sell，外資合計等於不含外資自營商＋外資自營商，自營商等於自行買賣＋避險。三類窗口為**外資及陸資（不含外資自營商）／投信／自營商合計**；三大法人合計只加這三類 net，外資自營商已計入自營商，不重加。窗口 sum 使用任意精度 canonical 整數字串、`unit=shares`，不轉浮點數、補零或縮窗。合法來源零保留零。

[官方日法人說明](https://www.tpex.org.tw/zh-tw/mainboard/trading/major-institutional/detail/day.html)的統計基礎是原始成交、不依券商錯帳／更正帳號調整後統計；這不等於下載資料永不修訂。每個 requested date 的錯日、selected 缺列／壞值、hash／receipt 不合格或競爭版本，均不採用該日、不得挑一版或較早替補。各 horizon 分別輸出 required／valid／missing／invalid dates、原因與逐日原值；5日齊備而20日缺較早日時，可僅5日 available。日曆或 policy 不合格則全窗口 fail closed。

`CapturedCSV` 保留 immutable body bytes、SHA-256、URL／method／資料日、policy／source version、HTTP／content type、UTC request／capture time；重驗 body hash、exact GET、2xx、identity encoding、CSV MIME／UTF-8與時間順序。`local_evidence_consistent` 只證本地 bytes／收據一致，caller 人造 capture 不證 HTTP 來源真實性。published／first available／revision time 均 unknown，本批是本次版本的資料日期事後統計，不作歷史決策、策略條件或趨勢輸入。

## 19. M1-W8：八截止法人來源與完整有界日曆

**W8 現行範圍：** 真8/25來源、完整27日曆、八截止96 net；支持TPEx3105／6488、2026-09-21／09-22／09-23／09-24／09-29／09-30／10-01／10-02，日曆限2026-08-25～10-02。§13 為共同基礎；W3～W7 已歸檔（見[現行節次索引](#現行節次索引)）。W8 不作implicit latest，也不放行新範圍。產品操作與不支持界線見[個股頁 §24](STOCK_RESEARCH_PAGE.md#24-m1-w8八截止法人窗口與原件追溯)。

### 19.1 新版policy、用途與取得上限

Worker `tpex-institutional-window/w8-v1`，profile `free_public_local`；外部pins為 `policy_version=m1-w8-tpex-window-2026-10-05.1`、`policy_digest=sha256:6a7e4aa786edf6ff801d411daeb254623ca9dce4815b771d51aa9a57e1da89cb`，canonical policy3613 UTF-8 bytes。完整policy／來源集合／四用途／八supported cutoffs與digest須一致；bundled registry／P2a manifest不變，舊version／pins不放行本版。

| Source ID | W8版本與准入查詢 |
| --- | --- |
| `tpex_government_institutional_csv` | `dataset-11856-dated-csv-observed-2026-10-05/v7`；沿[§13.1](#131-獨立-policy-與四用途)的dataset11856 exact GET，`d=115/MM/DD`僅8/25～10/2的27 expected sessions，不需8/24。 |
| `tpex_government_index_csv` | `dataset-11391-month-csv-observed-2026-10-05/v6`；沿§13.1的dataset11391 exact GET，`date=2026/08/01`／`2026/09/01`／`2026/10/01`，先驗全部返回月列再採有界日期。 |

Observed版本依actual Asia/Taipei2026-10-05，取得／capture另記UTC，不從branch或UTC日期推定。政府開放授權、TPEx署名、原始成交／外資不重加口徑沿§13.1／13.3；`local_fetch`／`raw_store`／`summarize`僅此policy admitted，`historical_pit=unsupported`。raw_store准入不授權本輪磁碟保存；原件只存process memory，其他標的金融值、日期、TWSE與任意自動下載未放行。

一次明示load最多30 GET＝3 month＋27 daily；daily≤2 MiB、index≤1 MiB、總≤57 MiB（59,768,832 bytes），每request timeout15秒、identity encoding、retry0／redirect0。日曆失敗不續取daily；一次嘗試後不重取、refresh或較早fallback。import／snapshot／普通GET零外網，不寫檔／DB；整批hard deadline、數字rate limit及跨程序limiter仍未提供。

### 19.2 全月驗證、27日曆與八截止

Calendar `tpex-2026-08-25_2026-10-02-weekdays-11503027221/v1`；周一至五與9/25、9/28 closure11503027221明示閉日，不由缺列推休市。三月43列＝8月21／9月20／10月2，先驗exact六欄、requested month、日期≤10/2、唯一／平日、有限正OHLC及上下界與有限漲跌；界線前壞值、錯月或重複也拒整份日曆。

`validation_scope=all_returned_month_rows`；8月candidate21／adopted5／pre-calendar16，只採8/25／8/26／8/27／8/28／8/31；9月20／20、10月2／2，其餘16列已驗未採。有界正面集合須恰等27 expected sessions；缺月／日、額外日期／閉日衝突或競爭版本使全部窗口unavailable。8/24等界線前index不代法人daily／用途准入。

計算版本 `independent-net-sum/expected-session-inclusive-v1`未變；每窗只採≤cutoff的required sessions，union較晚日不入較早窗口。

| cutoff | 截止內sessions | 5日起點 | 20日起點 |
| --- | ---: | --- | --- |
| 2026-09-21 | 20 | 2026-09-15 | 2026-08-25 |
| 2026-09-22 | 21 | 2026-09-16 | 2026-08-26 |
| 2026-09-23 | 22 | 2026-09-17 | 2026-08-27 |
| 2026-09-24 | 23 | 2026-09-18 | 2026-08-28 |
| 2026-09-29 | 24 | 2026-09-21 | 2026-08-31 |
| 2026-09-30 | 25 | 2026-09-22 | 2026-09-01 |
| 2026-10-01 | 26 | 2026-09-23 | 2026-09-02 |
| 2026-10-02 | 27 | 2026-09-24 | 2026-09-03 |

### 19.3 原件、精確整數與按窗口拒用

§13.3的25欄、全列日期／欄數／唯一合法code `[0-9A-Z]{4,6}`／非空名稱、selected兩股各22金融欄canonical int64、七組buy－sell／外資、自營商及total關係、股單位與任意精度sum不變；其他標的金融值未驗。缺／錯／壞日、selected缺列、hash／receipt不合格或競爭revision只拒需要該日的窗口；不補零、縮窗、挑版或較早／未來替代，policy／日曆壞則全部拒用。

各窗列required／valid／missing／invalid dates、原因、原列／版本／hash及UTC收據，讀回重驗同immutable bytes。published／first available／revision time、修訂保障／lineage仍unknown；事後統計非PIT、trend／研究條件、Signal、原件保存或跨程序重播。

### 19.4 唯一96 net參考

本版唯一96值集中下表，順序外資（不含外資自營商）／投信／自營商，單位股：

| 標的 | cutoff | 5日net | 20日net |
| --- | --- | --- | --- |
| 3105 | 2026-09-21 | `[9037200, 4201100, 1308054]` | `[8785685, 24565975, 1621385]` |
| 3105 | 2026-09-22 | `[12383787, 2617100, 1844118]` | `[11235554, 24828975, 1650797]` |
| 3105 | 2026-09-23 | `[8051509, 3386100, 1291688]` | `[4039680, 21243975, 1345760]` |
| 3105 | 2026-09-24 | `[11619934, 2453900, 554128]` | `[3598977, 20383588, 492586]` |
| 3105 | 2026-09-29 | `[1233280, 2655000, -140568]` | `[709262, 18045588, 543694]` |
| 3105 | 2026-09-30 | `[16854574, 2227000, 975486]` | `[19834870, 17802588, 1159585]` |
| 3105 | 2026-10-01 | `[10450479, 3045800, 345161]` | `[11360445, 16718388, -227745]` |
| 3105 | 2026-10-02 | `[21655769, 2223800, 1578271]` | `[25496297, 16596388, 1183894]` |
| 6488 | 2026-09-21 | `[-2861428, -167119, -97718]` | `[-12434698, -3998093, -195845]` |
| 6488 | 2026-09-22 | `[-1279737, -173308, 81702]` | `[-9048340, -4282803, -48947]` |
| 6488 | 2026-09-23 | `[-7129861, 121692, 168117]` | `[-12192815, -3478626, -182918]` |
| 6488 | 2026-09-24 | `[-7696805, 222092, 103774]` | `[-14680682, -3475784, -500087]` |
| 6488 | 2026-09-29 | `[-8857542, 285175, -12038]` | `[-13581580, -3551184, -446637]` |
| 6488 | 2026-09-30 | `[-3715832, 180211, 77751]` | `[-8274270, -2271295, -104392]` |
| 6488 | 2026-10-01 | `[-7671733, 1177490, 60743]` | `[-14064055, -1335785, -142974]` |
| 6488 | 2026-10-02 | `[-2452286, 920329, 229491]` | `[-13191795, -1012703, 261501]` |

有限接受不證範圍外／TWSE、修訂／PIT、trend／研究條件／Signal、raw保存／跨程序讀回或完整M1。

## 20. M1-PRICE-1：TPEx 兩股單日價格來源與准入

範圍只限TPEx3105／6488、2026-10-05單日價量（§20.7 另有2026-10-06兩股 tuple）；本來源獨立於原四來源registry、P2a及W8法人policy。產品操作與不支持界線見[個股頁 §25](STOCK_RESEARCH_PAGE.md#25-m1-price-1上櫃兩股單日價量閉環有限接受)。

### 20.1 Exact資源、用途與固定policy

來源ID為 `tpex_11370_daily_close_csv`、source_version為 `tpex-11370/2026-10-05`；官方[dataset11370「上櫃股票行情」](https://data.gov.tw/dataset/11370)所連唯一exact GET資源為 [CSV](https://www.tpex.org.tw/web/stock/aftertrading/DAILY_CLOSE_quotes/stk_quote_result.php?l=zh-tw&o=data)。限公開免費本地使用、TPEx／stock／TWD、3105穩懋與6488環球晶、quote-date 2026-10-05；不外推其他stock／ETF／指數或新日期。

Wrapper須正面核對instrument的market=TW／exchange=TPEx、selected symbol＋exact known name、instrument類型為stock及etf_category為空，才可按兩股policy scope固定TWD。原Instrument未有currency欄，DB／model未改；未來若有currency欄且非TWD須拒用。此來源typed memory明示TWD，unknown／mixed來源與其他市場不猜幣別。

獨立嵌入policy `policy_version=m1-price-tpex-11370-2026-10-05.1`，canonical UTF-8 1462B，`policy_digest=sha256:452b9b8cfa3d050b79ea1a85b3e4ed643c40cf3d17882b8cb809ffdb7143deea`；完整policy／來源／範圍與digest須一致。既有TWSE／global registry、bundled default與法人pins維持。

准入依dataset11370的[政府資料開放授權條款第1版](https://data.gov.tw/license)及既有[TPEx網站條款](https://www.tpex.org.tw/zh-tw/gtsm_disclaimer.html?l=zh-tw)第7點政府開放資料例外；第5點的自動下載限制未由可讀endpoint略過。此exact政府資源的 `local_fetch`、`raw_store`、`summarize` 有限admitted，仍須有界取得、顯名、完整性、原件hash／版本／時間及traceability；本輪只process memory，raw_store准入沒有授權磁碟保存。署名保留「證期局＋櫃買中心／上櫃股票行情／2026／OGL1.0」，data-date為2026-10-05。不放行legacy POST、附加 `d` 的歷史查詢、其他URL或任意自動下載，`historical_pit=unsupported`。

每程序首次合法明示POST最多1外部GET；重複POST／普通GET／切股cache不新增外網，失敗cache不自動retry。body≤3MiB（3,145,728B）、deadline30秒、redirect0／retry0；固定 `expected_body_sha256=bdfcead65b5c36d2bd75d20fe7b790fa56ce39d2547d0772989243550ca36149`。URL無歷史日期參數，返回不同body／日期不得悄悄換版或重試。只有quote-date及observed capture；精確publication／first available／revision、rate limit及endpoint SLA仍未證實。

### 20.2 2026-10-05 兩股金融值

10/05 body：HTTP200／application CSV、1,773,012B，12,060 data rows／18 fields，ROC `1151005` 對應2026-10-05、date-code唯一，SHA 同 §20.1；金融驗證僅兩股。data ordinal 為 1-based 資料列，含 header 行號另列。

| Selected股／data列序（1-based）／含header行號 | O／H／L／C（元／股） | 成交股數（canonical股） | 日常成交量（張） | 成交金額（元） |
| --- | --- | --- | --- | --- |
| 3105穩懋／205／206 | 614／630／604／615 | 48127911 | 48,127.911 | 29694939981 |
| 6488環球晶／717／718 | 1220／1235／1175／1180 | 18982607 | 18,982.607 | 22887612060 |

### 20.7 M2-FOCUS-DAY-RANGE-1：新日期來源准入與本日振幅 consumer

新policy `m1-price-tpex-11370-2026-10-06.1`，source_version `tpex-11370/2026-10-06`；以舊policy deepcopy只改version、scope.cutoff、新expected body SHA及attribution.release_version=`data-date-2026-10-06`。Canonical UTF-8仍1462B，digest `sha256:fc7b1451f6ae47145a5b40c3e08cdcad7ac8b9dafc64c7bf89f95c67cfefc288`；用途／exact URL／兩股／stock／TWD／process_memory及1 GET／3MiB／30秒／redirect0／retry0不變。原10/05完整policy／digest／body／金融表保留；程式准入只限已明確核准10/05、10/06兩immutable tuples，不自動接新日。10/05 worker m1-v1保持，新10/06 builder／worker `tpex-price-capture/m1-v2`；memory projection版本仍m1-v1。

10/06 body：1,788,599B／12,194 data rows／18欄，ROC1151006、全date-code唯一；SHA256 `aae44dcb35107299a9f2cd47191301fe2cc2d980b6eae152927587df015bfd9a`。

| 10/06 selected股／data ordinal／含header行號 | O／H／L／C原值（元／股） | 成交股數（canonical股） | 日常成交量（張） | 成交金額（TWD元） |
| --- | --- | --- | --- | --- |
| 3105穩懋／205／206 | 615.00／623.00／588.00／592.00 | 19731700 | 19,731.7 | 11863581093 |
| 6488環球晶／717／718 | 1175.00／1260.00／1145.00／1205.00 | 13913614 | 13,913.614 | 16835605385 |

兩股金融單位仍股、精確0.001張、TWD元及元／股；新表是來源版本實質變更，不覆寫10/05表。振幅分別精確`700/123`%及`460/47`%，O/C為down／up；產品精確門檻／四理由／五條件返回由[個股頁 §29](STOCK_RESEARCH_PAGE.md#29-m2-focus-day-range-1本日振幅與五條件往返)管理，不稱前日漲跌／ATR或策略。

Raw／receipt只memory、無DB IDs／行情原件保存；資料日10/06不等於即時或精確發布／首次可得／修訂，後三unknown、PIT unsupported，不外推歷史close／日曆／全市場或磁碟保存。

## 29. M2-FOCUS-STOCK-SCOPE-5：七股來源准入

default 10/06 的七股 scope（普通TPEx，新增6510精測），code順3105／3293／5274／5347／6488／6510／8069、quote-date2026-10-06；原六股canonical byte-equal。具名操作由[個股頁 §34](STOCK_RESEARCH_PAGE.md#34-m2-focus-stock-scope-5七股關注與同截止往返)管理。

### 29.1 10/06 價格 policy tuple 版本表

10/06 價格 scope 依序擴張時，每個版本都是獨立 immutable tuple，以 policy 版本、canonical 內容與外部 digest 共同識別；原 §21／§23／§25／§27 已歸檔，版本資料集中於下表。兩股 tuple 見 §20.1（10/05）與 §20.7（10/06）。來源資源與有限用途沿 §20.1 的 exact 政府 CSV：只 process memory，不放行磁碟保存、歷史日期參數或其他自動下載。`.1`～`.5` 共用 `expected_body_sha256`＝`ab34590df051d7ba08f35941811b69ee35f46c890212558b9f089119307b3200`（兩股 tuple 的 body SHA 見 §20.1、§20.7）。

| `m2-stock-scope-tpex-11370-2026-10-06.N` | 股數與 scope（code 順） | canonical UTF-8 | `policy_digest` | worker／projection | focus consumer |
| --- | --- | ---: | --- | --- | --- |
| `.1` | 3：3105／5347／6488 | 1484B | `sha256:6e662d5fc91957b586becdf41f351d5abf2c41cec09909de468e62e76cda4a78` | `tpex-price-capture/m2-stock-scope-v1`／`stock-price-memory/m2-stock-scope-v1` | `price-lot-focus/m2-v5` |
| `.2` | 4：3105／5274／5347／6488 | 1500B | `sha256:eb378f12e85462855d8271f1e977e4e84878882dd0944c004840a2ad21ab4434` | `tpex-price-capture/m2-stock-scope-v2`／`stock-price-memory/m2-stock-scope-v2` | `price-lot-focus/m2-v6` |
| `.3` | 5：3105／3293／5274／5347／6488 | 1516B | `sha256:57fb2dd808d71d43e89aca3fb42ef8dc53d9338093dd92a296858e62c41152ca` | `tpex-price-capture/m2-stock-scope-v3`／`stock-price-memory/m2-stock-scope-v3` | `price-lot-focus/m2-v7` |
| `.4` | 6：3105／3293／5274／5347／6488／8069 | 1532B | `sha256:03738997b4d8ec27872c58cfedef75c602aa17251b4a7724d1a375b6b85d8afc` | `tpex-price-capture/m2-stock-scope-v4`／`stock-price-memory/m2-stock-scope-v4` | `price-lot-focus/m2-v8` |
| `.5` | 7：3105／3293／5274／5347／6488／6510／8069 | 1548B | `sha256:5e397d1e560860208e11c8877fe539f38701757f8ba48dc6e7fea8ef8c0c4040` | `tpex-price-capture/m2-stock-scope-v5`／`stock-price-memory/m2-stock-scope-v5` | `price-lot-focus/m2-v9` |

Default10/06採最新 tuple（現為 `.5` 七股）；explicit 舊 tuple 及更早的10/05、10/06兩股 tuple 保持各自的 immutable 字典、pins 與 scope，不把新增股灌入舊 policy。既有10/06兩股 backend producer＝m2-v5，frontend legacy consumer 接受 m2-v4 相容。公開 URL 條件仍原五條件，policy 選擇是內部設定，不新增第六個公開條件。

## 30. M1-PRICE-SAVE-1：私人單日保存與跨程序讀回

本節定義 TPEx 七股／2026-10-06 完整原件的私人保存與跨程序重驗。Scope仍3105／3293／5274／5347／6488／6510／8069、ordinary stock／TWD；操作由[個股頁 §35](STOCK_RESEARCH_PAGE.md#35-m1-price-save-1私人單日保存與跨程序操作)管理。§29的`.5` process-memory capture／pins／金融值全留；新增獨立storage overlay，不改原capture事實。

### 30.1 Fresh用途與獨立storage版本

Exact政府daily CSV linkage不變；政府例外、local copy、署名與完整性支持有限私人保存，未准入普通股月歷史或任意自動下載。

Storage policy `m1-price-save-tpex-11370-2026-10-06.1` canonical UTF-8 2437B、digest `sha256:0e0d9f77fdfa97f2fe9864b9f1cfe2e73429899f1e0aea6c006c7630f0d7201e`；須同時核原`.5` capture pins及新storage pins。保存對象是已准入、完整可重驗的capture；原receipt仍`storage=process_memory`，不改寫成落盤capture。Storage receipt `tpex-price-storage-receipt/m1-v1`另記`storage=private_local`；projection為`stock-price-saved/m1-v1`。不自動變更default date／pins、fetch、hydrate或正式DB。

### 30.2 三檔、原子出版與嚴格重驗

唯一bundle literal files為`body.csv`、`capture-receipt.json`、`storage-receipt.json`。前兩者保持完整原body及原canonical receipt bytes；storage receipt exact schema含`version`／`storage`、storage/capture policy version＋digest、source identity/version／endpoint／GET／as_of／selected_symbols、body SHA/bytes、capture receipt SHA/bytes、request_started_at／captured_at／saved_at、attribution與limitations。Saved time須為aware UTC且不早於capture；它不是publication／first availability／revision。

先驗完整raw、canonical／schema／receipt／pins／來源日期與七股，再在exclusive staging建三檔並atomic rename至唯一final目錄。既有final須完整驗證；idempotent回傳既有bytes／saved_at，不覆寫或挑其他版。NEW process重開再驗完整body、兩份canonical receipt exact bytes及所有上述關係，不以selected projection替代fullbody hash；缺檔、部分bundle、污染／schema／pin／日期衝突均拒用，不較早fallback。API不以saved檔自動hydrate memory Store，原DB IDs仍null。

Windows private path保護目前只驗Windows；未提供其他平台保證。核定product root為`C:/Users/YiCheng/AppData/Local/taiwan-stock-research/price-save-01a11367`，final子目錄`tpex-11370-2026-10-06-m1-v1`；max one bundle／3files、raw≤3MiB、capture receipt≤8KiB、storage receipt≤16KiB、合計≤3170304B。測試quota、精確殘留及清理拒絕由[開發入口](development-baseline/README.md#m1-price-save-1-私人磁碟保存與新程序驗證入口)詳述；本准入不是其他scope的磁碟grant。

私人三檔（1791644B／3files／3 dirs）已達 file count cap：不新增磁碟案例，也不 copy／export／publish。其清理曾在 CreateProcess 前被 automatic review 以 `blocked by policy` 拒絕，維持 STRICT NO-RETRY：不換工具／路徑／owner，不逐檔、rename 或以 containing tree 繞過；狀態與接手查[治理 #1](https://github.com/YiCheng0608/stock-lab/issues/1)與原 Issue。

## 31. M1-CHIPS-CUTOFF-1006-1：同10/06法人窗口與完整有界日曆

本節定義 explicit 10/06 同截止法人窗口的來源用途、完整24日曆與金融真值。僅TPEx3105穩懋／6488環球晶、explicit `as_of=2026-10-06`；原件為當次事後觀測、process memory，非PIT。§19 W8的3613B canonical／SHA `6a7e4aa786edf6ff801d411daeb254623ca9dce4815b771d51aa9a57e1da89cb`、截止10/02及worker／API pins immutable；舊六價格canonicals與default日期不自動提升。產品操作見[個股頁 §36](STOCK_RESEARCH_PAGE.md#36-m1-chips-cutoff-1006-1同截止法人窗口與完整日曆)。

### 31.1 Exact集合、用途與版本

新policy `m1-chips-cutoff-tpex-2026-10-06.1`，profile `free_public_local`；canonical UTF-8 **4264B**，外部 `policy_digest=sha256:36c761a5f6e22afee86ad414769b88c06e97ae792141879a5660cf0856c180d5`。完整policy／exact集合／用途／scope及digest須同時匹配，不能自行計算expected pin或沿用W8、global registry、單日price／private storage grant。

| Source ID／observed版本 | 准入GET資源與exact參數 |
| --- | --- |
| `tpex_government_index_csv`／`dataset-11391-month-csv-observed-2026-10-07/chips-v1` | [dataset11391](https://data.gov.tw/dataset/11391) exact [inx](https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?response=data)，`date=2026/09/01`及`2026/10/01`（wire依URL encoding）；先驗全部返回月列。 |
| `tpex_government_institutional_csv`／`dataset-11856-dated-csv-observed-2026-10-07/chips-v1` | [dataset11856](https://data.gov.tw/dataset/11856) exact [dated daily](https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data)，`d=115/MM/DD`只限下述20 required sessions。 |

Root先核REST兩dataset、[OGL1.0](https://data.gov.tw/license)、[TPEx條款](https://www.tpex.org.tw/zh-tw/gtsm_disclaimer.html?l=zh-tw)第7點政府開放資料例外、[平日交易規則](https://www.tpex.org.tw/zh-tw/mainboard/trading/rules/system.html)與[11503027221休市公告](https://www.tpex.org.tw/storage/eb_data/11509/11503027221.html)。第5點限制不因endpoint可讀而消失；新grant只准此集合的 `local_fetch/raw_store/summarize`，raw_store本輪只process memory，不授權磁碟／正式DB或任意自動下載。署名保留櫃買中心、兩dataset、OGL1.0及資料／觀測版本；publication、first availability、revision time／lineage與數字rate limit未知，`historical_pit=unsupported`。

Worker `tpex-institutional-window/chips-1006-v1`；summary `tpex-institutional-window-summary/chips-1006-v1`、capture `tpex-institutional-memory-capture/chips-1006-v1`、calendar schema `tpex-observed-calendar/chips-1006-v1`。API `institutional-windows/chips-1006-v1`／read schema `institutional-windows-read/chips-1006-v1`；總覽 `stock-overview/chips-1006-v1`只在explicit10/06選取。計算仍 `independent-net-sum/expected-session-inclusive-v1`。

### 31.2 24日完整觀測日曆與20日金融集合

Calendar version `tpex-2026-09-01_2026-10-06-weekdays-11503027221/chips-v1`；9/1～10/6周一至五扣除公告明示9/25、9/28閉日，須與兩月全部返回正面集合exact相等。Sep20＋Oct4＝24；不從缺列推休市、不採10/06後資料，不以index替daily。

- Sep20：9/1、2、3、4、7、8、9、10、11、14、15、16、17、18、21、22、23、24、29、30。
- Oct4：10/1、2、5、6。
- 20日daily：上述集合最後20日，9/7～10/6；5日為9/30、10/1、10/2、10/5、10/6。

全返回24列先驗exact六欄／Gregorian日期、requested month、唯一平日、finite正OHLC及上下界／漲跌；全部144 calendar原欄受驗，較早9/1～9/4也不能略驗。缺月／日、額外日期、閉日衝突、future、壞列或版本衝突使日曆不可用。日曆完整不代表股票20／21日close或strategy inputs已取得。

Daily沿[§13.3](#133-原件整數及缺日契約)的25欄、日期／欄數／唯一合法code與非空名稱、selected各22金融canonical int64、七組buy−sell及外資／自營商／total關係；全18,098列結構驗證與兩股40 selected／1000原字串／880金融欄逐欄驗證分開，不外推其他股金融coverage。每窗只採≤10/06 required日期、任意精度sum；缺／壞日、selected缺列／競爭版本／hash或receipt不合格按所需窗口拒用，不補0、縮窗、挑版或取較早／未來替代。

### 31.3 一次取得與可證執行上限

空新Store只在首次合法explicit POST一次取得2 index＋20 daily＝**22 one-shot GET**；held read／普通GET／import不新增source，失敗不retry／refresh，無磁碟／DB。每次request起點設定httpx network timeout為min(15s, batch剩餘budget)，約束各次I/O等待而非整個request wall duration；index≤1MiB、daily≤2MiB、aggregate≤42MiB；180s batch budget在response／chunk邊界檢查，**不是OS硬搶占deadline**。Response header收到後限制≤16KiB，非socket-level header搶占；retained graph≤64MiB為deduplicated `sys.getsizeof`估算，不是RSS／peak。Redirect0／retry0／identity encoding；calendar失敗不續取daily。

### 31.4 12 net 金融真值

唯一金融真值集中下表，順序外資（不含外資自營商）／投信／自營商，單位canonical股；日常UI依穩定張公式除1000、最多三位小數去尾零：

| 標的 | 5日net（9/30～10/6） | 20日net（9/7～10/6） |
| --- | --- | --- |
| 3105穩懋 | `[27460450, 2352400, 2227304]` | `[36689368, 17747988, 2886699]` |
| 6488環球晶 | `[594644, 1330929, -11515]` | `[-14155476, -553503, -367682]` |

## 32. M1-SAVED-PRICE-FOCUS-1006-1：保存來源的七股關注准入

本節定義七股／2026-10-06 保存來源的四項條件篩選用途與精確契約。只含3105穩懋／3293鈊象／5274信驊／5347世界／6488環球晶／6510精測／8069元太，TW／TPEx ordinary stock／TWD，code升序。使用者操作由[個股頁 §37](STOCK_RESEARCH_PAGE.md#37-m1-saved-price-focus-1006-1保存來源關注與同截止往返)管理；§29 memory focus、§30私人保存及§31法人窗口各自保留原契約。

### 32.1 先准入只讀用途，再讀既有原件

本root在private read／implementation前於原task核定finite saved read-use。依§30已接受的政府例外、local private copy、署名與完整性，只准既有三檔的本機只讀重驗及有限衍生，不新增metadata／financial GET、複製、export／publish、hydrate、磁碟保存或正式DB用途。此准入不繼承未採來源的history／PIT／自動下載權，也不改default。

新consumer policy `m1-saved-price-focus-tpex-11370-2026-10-06.1` canonical UTF-8 **2677B**，外部digest `sha256:93059779e66d7826818db4a9eb9ea0a6856d631234b0efaa93c98241d6e5de3b`；projection `price-saved-focus/m1-v1`。須另核原capture `m2-stock-scope-tpex-11370-2026-10-06.5`／digest `sha256:5e397d1e560860208e11c8877fe539f38701757f8ba48dc6e7fea8ef8c0c4040`，及storage `m1-price-save-tpex-11370-2026-10-06.1`／digest `sha256:0e0d9f77fdfa97f2fe9864b9f1cfe2e73429899f1e0aea6c006c7630f0d7201e`。三種policy角色獨立；不把新consumer pins寫入原receipt或擴大七股scope。

唯一existing bundle為 `C:/Users/YiCheng/AppData/Local/taiwan-stock-research/price-save-01a11367/tpex-11370-2026-10-06-m1-v1/`。Literal三檔、原canonical schema／bytes／SHA及Windows path保護仍由[§30.2](#302-三檔原子出版與嚴格重驗)與[§33.2](#332-existing-private有限只讀)管理。原capture `storage=process_memory`／`request_count=1`是歷史capture事實；當前來源另標 `origin=private_local`、storage receipt仍 `private_local`。Augmented provenance不當作原canonical receipt重算hash。

### 32.2 完整重驗與有限衍生

每次合法snapshot重新驗完整body、兩份**原canonical** receipt、全部三檔full hash、source identity／version／endpoint／method／日期／七symbols、capture/storage/consumer pins與時間關係；不以selected projection代替body hash。全12194 data rows／18欄header、global width、ROC1151006與date-code唯一性受驗；金融值只宣稱七股126 source fields／42金融值，原字串保持。

Capture UTC `2026-10-06T23:32:21.005311+00:00`、saved UTC `2026-10-06T23:32:45.499432+00:00`保持；不等於publication／first availability／revision，後三unknown、historical_pit unsupported。Body1788599B、capture receipt1461B、storage receipt1584B，共1791644B／3files；hash 與 mtimeNS 見[§33.2](#332-existing-private有限只讀)。

Required七股先完整gate再filter；任一missing／invalid／conflict拒用，不跳壞股、縮scope、挑版、補零或較早／未來fallback。全七股合格才可available／count0。Canonical股與成交額是int64；張數精確除1000、最多三位小數，O/C方向只比較收盤與開盤。振幅為 `100×(H−L)/O`，OHLC按共同decimal scale化整數，inclusive門檻以 `100000×(Hscaled−Lscaled) >= minRangeThousandths×Oscaled` 核對；顯示「約」值不參與filter。

本次獨立真值如下，OHLC為元／股canonical值、成交額為TWD整數元；原source_fields的格式另保留，不以表內格式替代原列。

| 股號 | O／H／L／C | canonical股／精確張 | 成交額 |
| --- | --- | --- | --- |
| 3105 | 615／623／588／592 | 19731700／19731.7 | 11863581093 |
| 3293 | 794／794／772／780 | 1495462／1495.462 | 1164617657 |
| 5274 | 19520／19895／18855／18985 | 188693／188.693 | 3627465565 |
| 5347 | 184.5／195／184.5／191 | 34637793／34637.793 | 6615109776 |
| 6488 | 1175／1260／1145／1205 | 13913614／13913.614 | 16835605385 |
| 6510 | 3125／3140／3050／3055 | 560518／560.518 | 1729347985 |
| 8069 | 147／151.5／145／149 | 10796741／10796.741 | 1607943663 |

6510原漲跌字串 `-50.00 ` 含尾空白保持；它不是本consumer的C−O方向計算，不改成−70。來源金融權威只在本表詳述，操作門檻結果見§37。

### 32.3 讀取上限

每read 10s為read後與parse後的**cooperative檢查**，不是OS搶占或hard wall。單bundle／3files：raw≤3145728B、capture≤8192B、storage≤16384B、合計≤3170304B；retained graph≤32MiB為object graph估算，不是RSS／peak。超限／不合schema／hash／pins／日期的拒用與不讀unsupported日期界線由§37管理。

## 33. M1-SAVED-PRICE-CHIPS-INTEGRATION-1006-1：保存行情與法人窗口共同入口

保存行情與法人窗口共同入口：3105／6488 同 10/06 saved OHLC＋真5／20 net→追溯／五原條件 back。操作見[個股頁 §38](STOCK_RESEARCH_PAGE.md#38-m1-saved-price-chips-integration-1006-1共同入口與同截止往返)，§29～32保持。

### 33.1 先准共同用途，獨立核五份policy

ROOT在implementation/private read/financial GET前核joint policy `m1-saved-price-chips-integration-tpex-2026-10-06.1`：canonical UTF-8 **10702B**，SHA `a5e6ecda19952e4f6dc44ad9660e4cbbcc2e4a0a3670229ab63900cf74678d14`；consumer `saved-price-chips-entry/m1-v1`。外部version／digest及完整canonical同驗，received policy不自建expected pin；舊8853B draft未准。

| 獨立原policy／canonical bytes | SHA-256 | schema權威 |
| --- | --- | --- |
| `m2-stock-scope-tpex-11370-2026-10-06.5`／1548 | `5e397d1e560860208e11c8877fe539f38701757f8ba48dc6e7fea8ef8c0c4040` | §29 |
| `m1-price-save-tpex-11370-2026-10-06.1`／2437 | `0e0d9f77fdfa97f2fe9864b9f1cfe2e73429899f1e0aea6c006c7630f0d7201e` | §30 |
| `m1-saved-price-focus-tpex-11370-2026-10-06.1`／2677 | `93059779e66d7826818db4a9eb9ea0a6856d631234b0efaa93c98241d6e5de3b` | §32 |
| `m1-chips-cutoff-tpex-2026-10-06.1`／4264 | `36c761a5f6e22afee86ad414769b88c06e97ae792141879a5660cf0856c180d5` | §31 |

TW／TPEx ordinary stock／TWD price七identities：3105／3293／5274／5347／6488／6510／8069；institutional只3105／6488、explicit10/06。原capture process_memory／storage private_local及schemas獨立，joint不改receipt／default／W8／DB或hydrate。

### 33.2 Existing private有限只讀

唯一root `C:/Users/YiCheng/AppData/Local/taiwan-stock-research/price-save-01a11367`、bundle `tpex-11370-2026-10-06-m1-v1`；原1791644B／3files／3dirs全raw／canonical／mtimeNS重驗：

| literal file／bytes | SHA-256 | mtime_ns |
| --- | --- | --- |
| body.csv／1788599 | `ab34590df051d7ba08f35941811b69ee35f46c890212558b9f089119307b3200` | 1791329565505432100 |
| capture-receipt.json／1461 | `871a6887a3b87bd7c23c20fc3a25ec98d369d0df2ed8eedbe8cb040e5242cd36` | 1791329565507431000 |
| storage-receipt.json／1584 | `436465b4d13d604965327fe1be7eff98edf65274b0f16c7871474280feb0197b` | 1791329565509430100 |

Raw/capture/storage caps3145728/8192/16384B，bundle≤3170304B／one bundle。Shared64bundle/192file reads含ROOT，producer ceiling61＋ROOT3。Entry/apply/switch/back無明示read則private0。

Price UTC2026-10-06 started23:32:17.666931／captured23:32:21.005311／saved23:32:45.499432；publication/first availability/revision unknown、PIT unsupported。Snapshot10s cooperative／graph32MiB，非OS硬deadline/RSS/peak。

### 33.3 Fresh金融集合/guards

只准SINGLE NEW empty producer／capture_attempt1，external metadataGET0、price financialGET0；trusted首次chips POST才取得§31 exact2 index＋20daily＝22 official GET。API與preview各自在upstream前限 `POST /api/stocks/TPEx/(3105|6488)/institutional-windows/capture?as_of=2026-10-06`；query一次，非空UTF8 body≤4096B且須空JSON物件，壞body/query422、oversize413、其他POST405。其他五股不capture；GET unknown/duplicate query先422，舊/prices/saved405，focus unsupported日期先unavailable/private0。UI核saved detail context／五RAW。

僅admitted chips network context准exact HTTP／TPEx443 DNS-connect，redirect/retry0；index≤1MiB、daily≤2MiB、aggregate≤42MiB、received header≤16KiB。Request min(15s, remaining budget)、batch180s在response／chunk邊界檢查；chips64MiB／joint96MiB retained graph估算。非OS硬wall、socket header搶占或RSS／peak。

啟動時NEW price/chips/W8 Stores空／finance seed0。Current private read、chips capture／stock read／refetch或provenance核對失敗，同時mask saved prices／chart／raw與nets／calendar／dailyraw，保留ONE diagnostic。恢復須same context／generation兩次成功：明示NEW private snapshot＋明示held institutional read；held不外網refetch。舊generation成功不unmask，failed capture不retry／restart，無有效held raw維持unavailable。ROOT-only memory diagnostics／held原body＋receipt不capture/snapshot或回HTTP private fullbody。

## 34. M1-SAVED-PRICE-CHIPS-FOCUS-1006-1：保存行情與法人條件關注准入及日曆缺口

本節定義保存行情＋法人條件關注的新用途 policy 與八條件精確篩選契約（§34.1）；操作界線見[個股頁 §39](STOCK_RESEARCH_PAGE.md#39-m1-saved-price-chips-focus-1006-1八條件入口與不可用驗收邊界)，原§29～33契約不擴張。此 policy 沿原 immutable 10/06 schema／日曆：10 月 index 含 10/7 extra row 時拒用，不取 daily；日後 calendar 替代方案須另有 fresh parser／schema／policy／用途准入，不自動授權略過 extra date。

### 34.1 新用途及精確篩選契約

ROOT在implementation及兩項有限來源使用前准入 `m1-saved-price-chips-focus-tpex-2026-10-06.1`，canonical UTF-8 **14399B**、SHA `1b48fc6bb23b021f3d289c797b8d077af4576f492cbc08953d0515ef0da89416`；新schema `price-saved-chips-focus/m1-v1`。New pin與§33原capture／storage／saved-focus／chips／joint五組version/digest各自重驗；不以received policy自建expected pin，不改原schemas、W8、calendar、default、七股private pins或兩股chips scope。

新 `GET /api/focus/price-saved-chips`只接受一次且全部required的 `as_of/min_lots/day_move/min_turnover/min_range_pct/investor/horizon/min_net_lots`，body須0；missing／duplicate／unknown／invalid為422，unsupported cutoff先unavailable／private0。僅explicit2026-10-06；investor為foreign／trust／dealer、horizon原字串5或20。四price條件沿§32.2精確AND，再AND selected investor的true horizon net shares ≥ signed張門檻換算的shares，含等號，依code排序，不是ranking。

`min_net_lots`最多21字、grammar `-?(0|[1-9][0-9]*)([.][0-9]{1,3})?`，另拒negative zero、超出signed int64 shares、加號／空白／逗號／exponent／前導零。最多三位小數，以精確整數scaled1000，`-0.001`為-1股；不用浮點或顯示約值filter。Eight RAW原字串及尾零應保留。

Prices先完整驗原七股，joint候選只3105／6488；3293／5274／5347／6510／8069為scope排除，不記成法人零。Only ALL7 price＋BOTH chips來源／窗口完整並同cutoff／provenance才可宣告available count0；其他情況count=null／items=[]。同generation明示NEW private snapshot及held chips核對成功才能解除BOTH mask；失敗capture不可retry／restart／newproducer或hydrate舊memory。

## 35. M2-FOCUS-STOCK-SCOPE-6：八股與新來源日准入

`M2-FOCUS-STOCK-SCOPE-6-B1` 已有限接受 ordinary TPEx 新增6223旺矽、explicit2026-10-07的八股四條件操作。Code順3105／3293／5274／5347／6223／6488／6510／8069；原七組policy bytes與defaults、10/06七股private及兩股chips不變。具名操作由[個股頁 §40](STOCK_RESEARCH_PAGE.md#40-m2-focus-stock-scope-6八股四條件與同截止往返)管理，§20～34按原範圍保留。

### 35.1 身份、用途與新版本

ROOT的TPEx basic OBS2為原Date1151006／893列，核6223旺矽、掛牌20030106、industry24、preferred0／NTD10；准入operational ordinary TPEx／TWD。CFI與ISIN未核實，不能稱ISIN catalogue已驗或PIT membership。Metadata共7attempts，完整已知2052524B加未知partial；ISIN timeout與首次basic short-read的partial未知，原失敗留ROOT task，不宣稱全輪metadata bytes已知。

Fresh [政府dataset11370](https://data.gov.tw/api/v2/rest/dataset/11370)連至[exact TPEx daily CSV](https://www.tpex.org.tw/web/stock/aftertrading/DAILY_CLOSE_quotes/stk_quote_result.php?l=zh-tw&o=data)。本批依[OGL1.0](https://data.gov.tw/license)免費利用與署名要求、[TPEx條款](https://www.tpex.org.tw/zh-tw/gtsm_disclaimer.html?l=zh-tw)政府開放資料例外，先准入bounded process-memory用途；不授權保存、歷史參數或其他資源。引用／產品追溯仍須保留來源署名及原件完整性，精確metadata receipts以ROOT原task為準。

Implementation前准入新policy `m2-stock-scope-tpex-11370-2026-10-07.1`：canonical UTF-8 **1564B**，digest `sha256:bdad10af9090dd15319b3f3e8dca2952f75c4caf6d46b3032e706a5006ccbab2`；deep copy舊.5，只改version／cutoff／八股集合／bodySHA／release_version。新worker `tpex-price-capture/m2-stock-scope-v6`、projection `stock-price-memory/m2-stock-scope-v6`、consumer `price-lot-focus/m2-v10`，sourceversion `tpex-11370/2026-10-07`。10/07只explicit採用，不提升old defaults；不hydrate舊body或擴private／chips scope。

Finance quota為ROOT OBS1＋ONE empty producer FIRST各一次，**兩次已用盡**；body cap3MiB；已收headers16KiB後檢查，非socket cap；30s cooperative檢查，非OS preemption；graph32MiB estimate、redirect0／retry0／disk0。兩GET後禁retry／restart／newproducer；graph estimate不代表RSS或OS硬deadline。

### 35.2 原件與金融核對

| 本輪financial GET | 原始UTC start→capture | ORIGINAL receipt bytes／SHA-256 |
| --- | --- | --- |
| ROOT OBS1 | 2026-10-07T08:20:02.488665Z→08:20:11.382011Z | 1805B／`273abb5cbc48ac258ed30120e6c179e38a90a738d6ed4455a1f69023450c6b0e` |
| Actual empty producer FIRST | 2026-10-07T08:55:24.331973+00:00→08:55:32.267100+00:00 | 1468B／`d975da7dc97dec2755dd32f84cae14302c92fafcced71df07611f1e779e4cf3d` |

Financial GET總2、known3586610B；每份body1793305B、SHA `eaa1eaf37ff3e2305629dced8b0f6945a063b05841c69d75f826960e6bd819c8`，producer HTTP200。全部12245 data rows width18／Date1151007／date-code unique；ROOT在server停止前獨立核held raw及完整ORIGINAL receipt bytes、八股144原欄／48金融值，非replay／preload／disk。ROOT graph9010451B是retained estimate，非RSS。

6223已核O/H/L/C＝5590／5725／5480／5530元／股、canonical896441股＝896.441張、TWD成交額4984488555元，O/C為down。本日振幅沿既有exact公式；門檻4.382含6223、4.383排除6223，即使顯示「約4.383%」也不按約值filter。144原字串由實際追溯保留，不以本段格式替代raw。

Source-date10/07及capture UTC分開；publication／first availability／revision仍unknown、historical_pit unsupported。完整八股required reads及身份／金融／cutoff／pins／provenance先gate後filter，任一缺失或衝突仍unavailable/count=null/items=[]，不縮scope；只有完整八股available才可判真零。原精確張、int64 TWD、O/C及振幅公式不改。

### 35.3 接受與邊界

ROOT接受source14及本批coreoperation+1／standalone dependency0／reliability+1／stall1→0。API／trusted desktop及窄版同cutoff往返、真零與positive→HTTP502清值已驗；停止後detail錯誤actual NOT RUN，SSR不能代替。必要checks及owned退出見[開發入口](development-baseline/README.md#m2-focus-stock-scope-6-八股新來源日的零落盤驗證入口)。DOC review／freeze／qualified七分區索引／exact commit／另准master merge尚待，不回寫final hash。

本批privateIO0／chipsGET0／newdisk0；既有私人及DAY-RANGE保留fences不變。完整M1／M2／M3、ordinary20／21close history、strategy／time／PIT／Signal／Plan／execution仍未完成；index calendar不代ordinary closes。下一候選及新准入條件由[ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑)管理，本節不授予下一用途。

## 36. M1-SAVED-PRICE-CHIPS-FOCUS-CALENDAR-1006-2：全月日曆與八條件來源准入

本批已有限接受saved七股與TPEx3105／6488同explicit2026-10-06的八條件正向操作；新來源與舊§31／33／34各自獨立。§34的Oct10/7拒用及failed producer保留，不retry／restart／clone／hydrate；具名操作見[個股頁 §41](STOCK_RESEARCH_PAGE.md#41-m1-saved-price-chips-focus-calendar-1006-2八條件正向關注與同截止往返)。

### 36.1 新准入、全月驗證與採用集合

ROOT在implementation／GET／private read前於原task核定三份新canonical UTF-8 policy及外部固定pins；不由received policy自建expected pins：

| Policy version | Bytes／SHA-256 |
| --- | --- |
| m1-chips-cutoff-calendar-tpex-2026-10-06.2 | 5263／`1acf97b7dd0f13b9b49ed3293497e52ca52ea077256b8d99d9bc21ed5761d403` |
| m1-saved-price-chips-integration-calendar-tpex-2026-10-06.2 | 12009／`bfb9abeca3546f2dcedfcacaf5b3dece1709c05b49a839bce3fea5ded1936765` |
| m1-saved-price-chips-focus-calendar-tpex-2026-10-06.2 | 15487／`42c232a3f533683dce727ce1279e767038a6ee0f6295ce85b5aee07e998972bc` |

新worker／capture／summary／calendar／read使用 `chips-1006-calendar-v2`，entry `saved-price-chips-entry-calendar/m1-v2`、focus `price-saved-chips-focus-calendar/m1-v2`；calendar version `tpex-2026-09-01_2026-10-06-full-month-observed-2026-10-07-11503027221/chips-calendar-v2`。原capture1548B／storage2437B／saved-focus2677B pins、old chips／joint／focus、W8／defaults及身分scope保持，原精確公式見§32.2／34.1。

沿§31已核dataset11391／11856的exact用途、OGL1.0署名及TPEx政府開放資料例外；本批另准ONE新empty producer、memory-only有限22 GET，不取得metadata或普通股price。兩month index為2026/09/01及10/01，daily為9/07～10/06的既有exact20日期；原daily URL／query沿§31，redirect／retry0。新parser先驗ALL25原月列150欄及date uniqueness，再採≤10/06 exact24 observed dates；完整保留合法10/07原六欄供追溯但不採入窗口。9/25／9/28closure notice保持；last20為9/07～10/06、last5為9/30／10/01／10/02／10/05／10/06，不補零／縮窗／推休市／用index代ordinary stock closes。

### 36.2 Actual原件與獨立淨超

ONE trusted FIRST完成2index＋20daily＝22 GET／2907155B，UTC start2026-10-07T11:33:50.447150Z→final capture11:34:03.496330Z；無preload／replay／disk／metadataGET／ordinarypriceGET／restart。ROOT停止前獨立核ALL22 held body及ORIGINAL canonical receipt的完整bytes／SHA／UTC／policy／exact URL；daily全結構、日期、唯一alnum code及非空name已核，兩股40selected rows／1000原欄／880 int64與七組buy-sell-net／component relations、12nets獨立重算：

| 股／窗口 | 外資shares | 投信shares | 自營商shares |
| --- | --- | --- | --- |
| 3105／5 | 27460450 | 2352400 | 2227304 |
| 3105／20 | 36689368 | 17747988 | 2886699 |
| 6488／5 | 594644 | 1330929 | -11515 |
| 6488／20 | -14155476 | -553503 | -367682 |

外資不含外資自營商；canonical shares、精確張及口徑保持。Publication／first availability／revision unknown，historical PIT unsupported。新22使歷史已記錄GET70→92、known body8723075＋2907155＝11630230B；另有首次舊Sep未記錄bytes，不能稱全部歷史bytes已知。這些不擴大舊用途或授予下一capture。

Index1MiB／daily2MiB／aggregate42MiB、22 requests／ONE attempt／15s per-request及180s batch cooperative；received headers16KiB為收到後檢查，非socket硬cap。Chips retained graph3312443B是estimate，受64MiB界線；private32MiB／joint96MiB與10s snapshot也是estimate／cooperative，非RSSpeak／OS preemption。

### 36.3 Existing private與完整joint gate

唯一private root／bundle、三檔full bytes／SHA／mtimeNS、兩層UTC及ATCAP／NO-RETRY沿§33.2與[治理 #1](https://github.com/YiCheng0608/stock-lab/issues/1)，本批只准精確有限READ-only，不新增保存／copy／export／publish／delete。Producer新上限54snapshots、ROOT reserve3、新總57；承前7後shared≤64bundles／192logicalfiles，不能用oldconsumer96作本批上限。Actual26producer＋2ROOT＋inherited7＝35bundles／105logicalfiles，ROOT reserve1未用；ROOT兩次實讀含post-stop原三檔bytes／SHA／mtimeNS不變，children actualprivate0。

ALL7 price與BOTH3105／6488的完整calendar／20daily／5及20窗口、同cutoff／pins／provenance先gate再filter；其餘五股scope排除，非法人零。即使price條件先得零也不略chips驗證；只有完整available可count0，缺／衝突為count=null/items=[]。Signed張grammar／int64／inclusive AND沿§34.1；current failure mask兩來源，same-generation恢復須明示NEW private＋held chips兩次成功，held不外網重抓，舊generation不得回填。

### 36.4 接受與邊界

Coreoperation+1／standalone dependency0／reliability+1／stall0；source20及具名正向／真零／往返與focus、detail實際502清值已ROOT接受。負值card修正後僅SSR受驗，POSTFIX NEGATIVE CARD ACTUAL NOT RUN；actual missing-private-file及停止後恢復未跑。必要checks／owned退出見[開發入口](development-baseline/README.md#m1-saved-price-chips-focus-calendar-1006-2-全月日曆八條件的零落盤驗證入口)，freeze／qualified索引／commit／另准master merge待。

Private1791644B／3files／原3dirs ATCAP與preCreateProcess拒絕／process0/delete0 STRICT NO-RETRY不變；ENTIRE DAY-RANGE及.range-ui、TURNOVER／MAIN五unknown-owner cache／較舊資源全部保留，禁止替代tool/path/owner／逐檔／rename／containingtree或掃Temp/HAR/GPG/cache/log/history。完整M1／M2／M3、ordinary20/21closes／trend／strategy／time／PIT／execution仍缺；本批global daily codes/names受驗不代表另五股存在、identity-name／金融窗口已驗。下一scope須新ROOT准入，current22額度已用盡。

## 37. M1-SAVED-PRICE-CHIPS-FOCUS-STOCK-SCOPE-7-1006-1：七股共同來源准入

ROOT有限接受同explicit2026-10-06的saved七股＋七股法人共同範圍；新增3293鈊象／5274／5347／6510／8069，3105／6488也由本次新來源重驗。舊兩股§36及其政策、原件、失敗與未跑項保持；操作由[個股頁 §42](STOCK_RESEARCH_PAGE.md#42-m1-saved-price-chips-focus-stock-scope-7-1006-1七股八條件與同截止往返)管理，不回寫舊calendar negative card為已驗。

### 37.1 獨立准入、版本與來源集合

ROOT於2026-10-07T13:05:59Z先核定用途／有限來源／private READ與下列canonical UTF-8 policies及外部pins，才implementation／GET／private IO；不能從received policy自建expected digest。

| Policy version | Bytes／SHA-256 |
| --- | --- |
| m1-chips-cutoff-stock-scope-7-tpex-2026-10-06.1 | 6742／`b2f939100bd76de12bd974abb80f267596bf5a55f839271a5f4cc61409f9c220` |
| m1-saved-price-chips-integration-stock-scope-7-tpex-2026-10-06.1 | 13404／`8e55142cce367fd44d64ea9d6d9e756c1fdd5b091c928669bbe94de1df950de8` |
| m1-saved-price-chips-focus-stock-scope-7-tpex-2026-10-06.1 | 17021／`2f6d3a91337363e5700d7fdf6c16c63b8a14f45362d4407c8b73b01dabfe860e` |

New profile `free_public_local_full_month_cutoff_stock_scope_7`；worker `tpex-institutional-window/chips-1006-stock-scope-7-v1`，summary `tpex-institutional-window-summary/chips-1006-stock-scope-7-v1`，capture `tpex-institutional-memory-capture/chips-1006-stock-scope-7-v1`，calendar `tpex-observed-calendar/chips-1006-stock-scope-7-v1`。API `institutional-windows/chips-1006-stock-scope-7-v1`與read `institutional-windows-read/chips-1006-stock-scope-7-v1`分開；entry `saved-price-chips-entry-stock-scope-7/m1-v1`、focus `price-saved-chips-focus-stock-scope-7/m1-v1`。

Calendar version `tpex-2026-09-01_2026-10-06-full-month-observed-2026-10-07-11503027221/chips-stock-scope-7-v1`；daily/index source versions分別為 `dataset-11856-dated-csv-observed-2026-10-07/chips-stock-scope-7-v1`／`dataset-11391-month-csv-observed-2026-10-07/chips-stock-scope-7-v1`。Old pure/calendar全bytes、原三price policies／pins與defaults不改；七股普通TPEx／TWD身份與同10/06保存價格沿§29／32，法人identity/name另由本次140列逐列重驗。

沿§31已核dataset11391／11856 exact用途、OGL1.0署名及TPEx政府開放資料例外，另准ONE新empty producer、trusted FIRST一次、memory-only 2index＋20daily。Month index2026/09/01、10/01；ALL25原月列150欄與日期唯一性先驗，再採≤10/06 exact24，合法10/07原六欄保留但不進窗口。Last20為9/07～10/06，last5為9/30／10/01／10/02／10/05／10/06；9/25／9/28 closure notices保持。Exact daily URL/query沿§31；不補零／縮窗／推休市，index不能代ordinary stock closes。

### 37.2 Actual原件與42個精確窗口值

ONE fresh FIRST完成22 GET／2907155B，UTC start2026-10-07T13:38:40.408105Z→final13:39:05.175470Z。ROOT獨立核FULL22 held raw及ORIGINAL22 canonical receipts的完整bytes／SHA／時間／HTTP200 identity／exact URLs；global daily width25、date/code唯一、alnum code／非空name、七股140selected rows／3500原字串／3080 int64及全部buy-sell-net／component relations受驗。Full42 window totals獨立重算如下；canonical單位為股，精確張除1000。

| 股／窗口 | 外資shares | 投信shares | 自營商shares |
| --- | --- | --- | --- |
| 3105／5 | 27460450 | 2352400 | 2227304 |
| 3105／20 | 36689368 | 17747988 | 2886699 |
| 3293／5 | 5507085 | 420000 | -11177 |
| 3293／20 | 9668934 | 1500000 | 78845 |
| 5274／5 | -13315 | -66756 | 8894 |
| 5274／20 | 177907 | -18788 | -5046 |
| 5347／5 | 8820683 | 3720607 | 407416 |
| 5347／20 | 44867613 | 8655386 | 2676428 |
| 6488／5 | 594644 | 1330929 | -11515 |
| 6488／20 | -14155476 | -553503 | -367682 |
| 6510／5 | 87416 | -660897 | 43724 |
| 6510／20 | -319920 | -406908 | 99835 |
| 8069／5 | -4053731 | -9040 | 285782 |
| 8069／20 | -9278025 | -252940 | 294173 |

外資不含外資自營商；5／20／三類所有aggregate須在signed int64內，scope7專屬overflow guard拒越界，不影響old calendar版本。原精確價格／O-C方向／振幅式及signed張grammar／inclusive AND見§32.2／34.1，不改公式或用顯示約值filter。Publication／firstavailability／revision unknown，historical PIT unsupported。

Index1MiB／daily2MiB／aggregate42MiB、22 requests／ONE attempt／15s per-request／180s batch cooperative、received headers16KiB收到後檢查，非socket硬cap；chips graph4188503B是estimate，界線64MiB，private32MiB／joint96MiB及10s snapshot亦為estimate／cooperative，非RSS或construction peak／OS preemption。本次metadataGET0／ordinarypriceGET0／disk0／children actualIO0。歷史已記錄GET92＋22＝114、known11630230＋2907155＝14537385B，另有first old Sep未記錄body；不稱全部歷史bytes已知。Source22 SPENT，禁retry／restart／clone／replay／hydrate／preload／使用old capture取代新grant。

### 37.3 ALL7共同gate與private範圍

每次先完整ALL7 price＋ALL7 chips/calendar／20daily／5及20窗口／同cutoff／pins／provenance，再filter；高price門檻或先得零仍不得省略七股法人。Only full available才count0，missing／invalid／conflict為count=null/items=[]，不縮scope／跳壞股／補零。Initial saved unread只mask price，獨立核實held chips可呈現，但joint不ready；actual current source failure同時mask BOTH。恢復仍須same-generation明示NEW private＋held chips雙成功，未跑actual recovery。

Private exactroot／三檔full SHA／mtimeNS／原receipts／UTC沿§33.2及[治理 #1](https://github.com/YiCheng0608/stock-lab/issues/1)，只READ-only，禁止新增保存／copy／export／publish／delete。承前35bundles/105logicalfiles，新producer26＋ROOTreserve3＝29/87另准；實際producer26＋ROOT2，使FINAL63/189≤shared64/192，producer26 SPENT／ROOTreserve1未用；oldconsumer96不改，不reset quota，剩1bundle/3files非未來grant。

ROOT1 UTC13:11:03.008032Z～13:11:03.052032Z及finalROOT2 UTC14:03:55.687262Z～14:03:55.721262Z（均2026-10-07）獨立核完整三檔bytes／SHA／decimal mtime、全12194×18與七股原18欄；body1788599B＋capture1461B＋storage1584B＝1791644B與original JSON／mtime均不變。Children actualprivate0，沒有第三次ROOT讀取。

### 37.4 有限接受與下一缺口

ROOT接受source20及七股positive／verifiedzero／samecutoff七detail／八RAWback、新profile負值cards與actual502清兩來源；coreoperation+1／standalone coredependency0／reliability+1（scope7全7×2×3 aggregate int64 overflow guard）／stall0→0。Actual missing-private-file與post-stop recovery NOT RUN，synthetic不代actual；舊§36 negative card修正後native NOT RUN仍保持。Checks與退出見[開發入口](development-baseline/README.md#m1-saved-price-chips-focus-stock-scope-7-1006-1-七股八條件的零落盤驗證入口)；DOC review／freeze／qualified index／commit／另准master merge待。

Private3files1791644B＋original3dirs ATCAP／preCreateProcess approval REJECTED／process0/delete0 STRICT NO-RETRY，禁alternate tool/path/owner/tree bypass與新disk/copy/export/publish/delete。DAY/TURNOVER/MAIN五cache＋holiday/older資源排除及禁sweep完整條件見[治理 #1](https://github.com/YiCheng0608/stock-lab/issues/1)；清理與功能分報。

下一未准入 `M1-CHIPS-STOCK-SCOPE-7-DAILY-NET-TREND-20-1006-1-B1`以本次140原daily／42 totals支持七股每日net曲線／精確日期表／running cumulative新操作；條件及fresh finite source／new series policies/pins由[執行清單](ROADMAP_EXECUTION.md)管理。Current22非下一grant、next private actualIO0；ordinary20/21 closes／trend／strategy／time／PIT／execution仍缺。

## 38. M1-CHIPS-STOCK-SCOPE-7-DAILY-NET-TREND-20-1006-1：七股每日法人淨超與窗口累計

ROOT已有限接受本批chips-only核心操作；同explicit2026-10-06、普通TPEx／TWD七股3105／3293／5274／5347／6488／6510／8069，外資不含外資自營商、投信、自營商各別5／20日每日淨超及窗口累計。操作及actual邊界由[個股頁 §43](STOCK_RESEARCH_PAGE.md#43-m1-chips-stock-scope-7-daily-net-trend-20-1006-1七股每日淨超與累計操作)管理。本節新版本獨立；§37及old calendar政策、defaults、失敗、pending與未跑歷史原樣保持，不能以本次接受回寫舊驗收。

### 38.1 獨立政策與有界來源

ROOT原task的precise admission先於implementation／financial GET；獨立canonical policy `m1-chips-daily-net-series-stock-scope-7-tpex-2026-10-06.1`，9733 UTF-8 bytes，外部SHA-256 `143aabb4cd2d86110d5564793ce77b0fb6c60b3e603f23c1e188875934a48a31`。Expected pin不得由received policy自建。New profile `free_public_local_chips_only_daily_net_series_stock_scope_7`；worker `tpex-institutional-series/chips-stock-scope-7-v1`、capture `tpex-institutional-series-capture/chips-stock-scope-7-v1`、read `institutional-daily-net-series-read/chips-stock-scope-7-v1`，計算版本 `signed-daily-net-running-sum/window-reset-int64-v1`。Old producers／profiles immutable；只有純解析與數值函式可重用，不restart／clone／hydrate／replay／preload或用old capture取代新來源。

沿[§31](#31-m1-chips-cutoff-1006-1同1006法人窗口與完整有界日曆)的dataset11391／11856 exact用途、OGL1.0署名與TPEx政府資料例外，只另准ONE empty producer的FIRST一次：2份2026/09/01、10/01月index＋9/07～10/06 last20 daily，exact URL/query、HTTP200／CSV UTF-8／identity依canonical policy。Daily source version `dataset-11856-dated-csv-observed-2026-10-07/chips-daily-net-series-stock-scope-7-v1`；index為 `dataset-11391-month-csv-observed-2026-10-07/chips-daily-net-series-stock-scope-7-v1`。

先驗ALL25月原列／150原字串與日期唯一性，再採≤10/06 exact24；10/07六原欄保留追溯而不採入。Last20為9/07～10/06，last5為9/30、10/01、10/02、10/05、10/06；9/25／9/28 closure沿原契約。Index是observed calendar，不能當普通股收盤序列；缺列不推休市、不補零／縮窗／跳壞股。新觀測或來源不符合exact bound即停止，不重試或機械續抓。

### 38.2 每日、累計與完整性契約

Canonical為signed int64股，以canonical integer string傳遞；張精確除1000、最多三位小數，既有單位公式不改。各窗口從第一日前的0重新累計，按日期做exact prefix sum；5日不延用20日累計起點。每個dated point／row保留ALL25原字串、原列ordinal、body SHA-256、original canonical receipt SHA-256與calendar。

ALL7×兩窗口×三法人須完整驗daily、aggregate及每個running prefix，才可顯示任何available series或合法零。任一daily／aggregate／prefix超過−9223372036854775808～9223372036854775807，整個七股profile unavailable，不只拒目前所選股。ALL42期末累計必須等於獨立窗口淨超和；source relations與component檢查沿完整25欄口徑。Unknown／missing／conflict不能變0，亦不能以先得到零省略ALL7 gate。

### 38.3 本次actual來源與資源界線

ONE新API generation `7e5fb646-d205-4d77-b452-c459a0b10efd`，no seed／preloaded=false；native FIRST receipt `89e14f3d-83cc-4b36-975b-39e245e63f60`。2026-10-07 UTC16:07:22.869778～16:07:39.341222，22 GET／2907155B，全部HTTP200 identity。ROOT獨立核FULL22原body＋ORIGINAL22 canonical receipts的bytes／SHA／UTC／method／exact URL、全daily結構／日期／code／name／關係、ALL25 calendar採24排10/07、140 selected rows／3500原字串／3080 int64、ALL42窗口總和及525累計前綴。

Index1MiB／daily2MiB／aggregate42MiB、22 requests／ONE attempt／無redirect／retry；15s per request與180s batch為cooperative boundary checks，非OS強制中止。Received headers16KiB是收到後檢查，非socket硬cap；retained graph8748386B在64MiB estimate界線內，為deduplicated getsizeof estimate，非RSS／construction peak。GET診斷回應界線16MiB；process memory，new disk0。Publication／first availability／revision unknown，historical PIT unsupported；原成交統計未反映券商帳號更正。

Current metadataGET0／ordinarypriceGET0／privateactualIO0／upstreamPOST0；Source22 SPENT。Inherited114＋22＝136 chips GET，known17444540B另有first old Sep body unknown，不稱所有歷史bytes已知。控制項、返回及held READ不能重取得來源；FIRST不能重複。Private FINAL63bundles／189logicalfiles、剩1bundle／3files不是新grant／reset／retry／thirdROOTread；完整ATCAP、STRICT NO-RETRY及DAY／MAIN／其他資源fences見[治理 #1](https://github.com/YiCheng0608/stock-lab/issues/1)，本批不碰private。

### 38.4 有限接受與暫停

Coreoperation+1／standalone coredependency0／reliability+1（preview startup guard／CSS修正）／stall0→0。Actual當日零為3293／trust／2026-09-29，原列ordinal221；ALL42完整窗口總和均非零，不能稱actual零窗口。驗證命令、原exit及owned退出見[開發入口](development-baseline/README.md#m1-chips-stock-scope-7-daily-net-trend-20-1006-1-七股每日淨超的零落盤驗證入口)。

文件截止時DOC review／freeze／qualified indexes／commit／另准local master merge待；使用者要求完成本批合併後暫停，不啟動下一輪。未完成候選「M1普通股20／21交易日真實收盤序列與同截止趨勢接線」等待使用者恢復及新精確來源／rights／time／calendar／schema／profile／pins／finite quota准入，非可執行來源已取得；ordinary closes／股價trend／strategy／PIT／execution與完整ROADMAP仍未完成。

## 39. 2026-10-08：歷史收盤新候選審查與官方事件重選

本次新FinMind primary核對提供 [TaiwanStockPrice technical API線索](https://finmind.github.io/tutor/TaiwanMarket/Technical/)，與舊Sponsor broker候選分開。[2026-07-13使用條款](https://finmindtrade.com/analysis/#/Sponsor/terms_of_use)與[2026-07-12 disclaimer／licenses](https://finmindtrade.com/analysis/#/Sponsor/disclaimer)依方案界定API／SDK服務用途；服務不包含對外再散布／轉售／鏡像，對外公開仍須自行確認原資料機關授權要求。這些新證據尚未建立本專案exact普通股歷史source owner／rights／各用途與獨立calendar／consumer pins；MIT軟體license或一般公開管道聲明不代data permission。M1普通股20／21收盤候選仍未准入，不改成全域禁止；無新取得路徑不重複monthly／legacy審查。六次metadataGET已完成、金融GET／落盤0；完整收據留ROOT原task，不另建report或來源副本。

ROOT改選 `M2-OFFICIAL-EVENT-DATE-RANGE-20261008-1`，只沿[§9](#9-m1-p3atwt48u-selected-官方事件原件摘要)／[§11](#11-m2-p1本次官方事件-feed-摘要)已准入exact TWT48U／free_public_local／原registry、digest、sourceversion與pins。2026-10-08 Taipei的新核對為[政府dataset89748](https://data.gov.tw/dataset/89748)免費／OGL1.0／不定期、metadata詮釋更新2026-06-30；[TWSE Swagger](https://openapi.twse.com.tw/v1/swagger.json) info1.0、exact GET／十二string欄、Date為除權息日期。兩metadataGET完成，UTC2026-10-07T19:04:41～42，非金融原件；metadata更新日不是事件availability。ROOT另grant一次fresh financial GET，body≤5MiB、20秒per-operation／30秒cooperative／redirect0／retry0、body／receipt只RAM；本摘要核定時尚未取得，不沿用舊58列。range consumer／計數／產品數值與具名操作仍待final實作及ROOT驗收，不先改原契約；日期區間篩的是effective date，published／first available／revision／historical PIT支持不擴張。

### 39.1 M2-OFFICIAL-EVENT-DATE-RANGE-20261008-1：實際來源結果

ROOT已接受ONE fresh exact TWT48U金融GET，HTTP200／16876B／62事件62標的；request UTC2026-10-07T19:39:48.116667+00:00、captured19:39:48.192610+00:00，Taipei觀測日10/08。完整ORIGINAL body／receipt在同RAM物件受核，日期／分類／名稱／ordinal逐列對actual API；body SHA-256 `660bf15d488b36223c36c63cc7ec1bc7fc5339da36fed409e48eaa7748e31b3b`，receipt SHA-256 `2893769f263c3128746a169dff6c56cbd5bf5d9bbfb2a71f681e92fbbc44f6ed`。這是本次原件，非§11舊58列重播。

沿§9原source_version `twse-twt48u-all-d011-2026-09-12`、registry `r1-a1-c009-2026-09-12.1`、external digest `sha256:eb6c290d7716300c4117bb2cdc61a66cbf8d62e344870928933b44b77461f87b`，不改pins／原snapshot。新consumer `official-event-focus/p3-v1` 的range只投影effective date，完整feed／receipt驗後才篩選；精確計數、API及具名操作由[個股頁 §44](STOCK_RESEARCH_PAGE.md#44-m2-official-event-date-range-20261008-1官方事件日期區間與研究往返)管理。Published／first available／revision仍unknown，historical PIT unsupported；capture time不代發布，synthetic catalogue不證普通股／行情。

本輪metadata8 SPENT（FinMind6、TWT48U權利2）、金融1 SPENT；5MiB、20秒per-operation／30秒cooperative、redirect0／retry0與RAM用途維持。首次失敗亦耗額度、focus／selected共享seal，不跨入口自動再取。FinMind歷史金融GET0，exact data owner／use rights及獨立calendar仍缺，不因MIT授權放行；舊22／136／private remaining1不續grant。API正常結束後原件RAM釋放，無落盤／replay／restart；下一分類操作須新ROOT准入，完整metadata／command／exit收據留原task。

## 40. M2-OFFICIAL-EVENT-KIND-20261008-1/B1：事件類型實際來源與有限接受

2026-10-08。ROOT已有限接受新consumer `official-event-focus/p4-v1` 的精確息／權／權息配effective range／q；新metadata4（兩official web＋兩direct requests）與金融1均SPENT。完整feed先驗後篩，API及可信desktop／窄版操作見[個股頁](STOCK_RESEARCH_PAGE.md) §45。本節只更新本輪§40，§39與既有pins保持。

[Gov REST dataset89748](https://data.gov.tw/api/v2/rest/dataset/89748)：HTTP200／2658B，SHA-256 `d0227595f62abe139128aeac295231f1c2ce40d850b4724180ed52af062dd1b0`，UTC2026-10-07T20:44:58.522584Z～20:44:58.711184Z。上市股票除權除息預告表、cost free／license1／irregular，metadata modified2026-06-30；distribution 是 TWSE exchangeReport 的 response=open_data CSV URL，notes 指向 Swagger 與 OGL。metadata 更新日不代事件 availability。

[TWSE Swagger](https://openapi.twse.com.tw/v1/swagger.json)：HTTP200／309960B，SHA-256 `06e1cea82448361e733a0ad1ae16e52f5d5d6b71905acd078472f852c32c0eb0`，UTC2026-10-07T20:44:58.711184Z～20:44:58.821751Z；Swagger2.0／info1.0／HTTPS，exact GET `/exchangeReport/TWT48U_ALL`、owner TWSE、十二 string fields／未宣告 auth，Date 為除權息生效日。ROOT 已核 linked doc 與 exact same operation 映射。

ROOT 本次核[OGL1.0](https://data.gov.tw/license)與[TWSE 使用條款](https://www.twse.com.tw/zh/terms/use.html)第6同意方式／第8政府資料例外；兩者是 parsed pages，不虛構 raw HTTP／SHA，未另取得 Swagger info 裡舊 page/terms 路徑。local_fetch／raw_store 僅 RAM，summarize 保留 TWSE 署名、完整性及 trace。registry `r1-a1-c009-2026-09-12.1`、external digest `sha256:eb6c290d7716300c4117bb2cdc61a66cbf8d62e344870928933b44b77461f87b`、source_version `twse-twt48u-all-d011-2026-09-12`／free_public_local 與原雙 pins 不改。

可信可見FIRST觸發新empty OfficialEventMemory generation `49e5b5c3-88a8-4b78-83d3-a1fdf798b19c`，ONE exact HTTPS GET `/exchangeReport/TWT48U_ALL`：HTTP200／16876B／62事件62標的，UTC2026-10-07T21:14:07.222732+00:00～21:14:07.267759+00:00，Taipei觀測10/08。body SHA-256 `660bf15d488b36223c36c63cc7ec1bc7fc5339da36fed409e48eaa7748e31b3b`；ORIGINAL receipt4463B、SHA-256 `c2b0ae35a19c55ab198173cc1eb14951552b677fd0edd867d7c0ab067e59ad86`。body SHA同前輪，新GET／empty generation／新receipt及兩same_object核對證明本批fresh來源；全62×12原string（744）／使用欄位映射及ordinal逐列核，息55／權6／權息1。

5MiB／identity／核定per-operation上限20秒、實際httpx15秒／30秒cooperative，非hard deadline；retry／redirect／warmup0、首次失敗亦SPENT／共享seal。15focus＋8detail＋4cached POST＋4unavailable與8invalid先拒422已接受，最終source_gets1／guards0／private_reads0。完整原件／receipt只同RAM snapshot；API結束後釋放，禁舊原件／producer reuse、restart／replay／preload／hydrate。舊metadata8／finance1、22／136／private remaining1不續grant，privateIO／新增test及product檔案0B，indexcache另報；完整收據留ROOT原task。

本能力只按Date生效日，不需交易日calendar；published／first availability／revision unknown，historical PIT unsupported。synthetic4（0056 ETF／1449／1463／2614）只routing，不證ordinary／行情／全市場；payout numeric／forecast／Plan／save未驗。M1歷史closes權利／calendar仍缺新路徑，不重審。本批actual核心操作+1／standalone dependency0／reliability0／stall0→0，metadata／DOC本身不增核心或reset，完整M1／M2／M3未完成；[執行清單](ROADMAP_EXECUTION.md)管理版本待辦。

## 41. M1-TWSE-ISSUER-EVENT-PROFILE-20261008-1/B1：真 issuer 與同截止事件有限接受

2026-10-08。ROOT已有限接受1449／1463／2614真TWSE公司六原欄trace、同cutoff官方事件與原五條件返回；完整新issuer／event body及ORIGINAL receipt同heldobjects、全原string／映射／dates／ordinals／dualSHA已獨立逐列驗。metadata5 NEW（official dataset search／OGL／TWSE terms三parsed＋Swagger／Gov兩raw）及financial2均SPENT；local_fetch／raw_store只RAM／summarize須TWSE署名、完整性／追溯，不含磁碟／private／account／historical PIT授權。行為與具名操作見[個股頁 §46](STOCK_RESEARCH_PAGE.md)。

[Gov dataset18419](https://data.gov.tw/api/v2/rest/dataset/18419)：HTTP200／4759B、SHA-256 `a12cfebfba57d5666d12c57f1e094a7802b001359d2c189c5857cb1f6d19b6d9`，UTC `2026-10-07T22:35:06.570713+00:00`～`2026-10-07T22:35:06.872799+00:00`；license1／costfree、modified2024-11-25，distribution CSV `https://mopsfin.twse.com.tw/opendata/t187ap03_L.csv`，notes明示Swagger。此Gov請求只取得metadata，modified不代公司出表／availability，CSV金融原件未取。

[TWSE Swagger](https://openapi.twse.com.tw/v1/swagger.json)：HTTP200／309960B、SHA-256 `06e1cea82448361e733a0ad1ae16e52f5d5d6b71905acd078472f852c32c0eb0`，UTC `2026-10-07T22:34:44.589098+00:00`～`2026-10-07T22:34:44.954299+00:00`；exact HTTPS GET `/opendata/t187ap03_L` 宣告33 string fields，exact TWT48U12欄保持。本批金融top-array／全33原string及schema已由actual FIRST／ROOT核，不只憑Swagger當transport通過。

ROOT核[OGL1.0](https://data.gov.tw/license)／[TWSE使用條款](https://www.twse.com.tw/zh/terms/use.html)第6approved method／第8政府資料例外，連同official dataset search為parsed；沒有raw HTTP／SHA就不捏造。新獨立[issuer code manifest](../backend/worker/twse_issuer_registry.json)：sourceversion `twse-t187ap03-l-d18419-2026-10-08`、registry `twse-issuer-r1-2026-10-08.1`／external digest `sha256:7488da20a3bdf94aaa548c896d19077628bf93529208226d49b2a02896972f89`、source profile `twse_issuer_free_public_local`；consumer `twse-issuer-event-profile/m1-v1`／external policy digest `sha256:02bf2422129c46490516557bccd188f7d550d2516c4b5e49e9acc2faf5338244` 已ROOT review。DOC不另建manifest附件；原四source／defaults／pins及§40完整不變。

### 41.1 本批兩份 FIRST 原件

可信loopback FIRST先取得fresh TWT48U，再取得issuer，各producer ONE exact HTTPS GET／NEW empty獨立generation／single attempt，FIRST失敗亦SPENT；5MiB／identity／per-operation上限20秒（實際timeout15）／30秒cooperative非deadline、redirect／retry／warmup0。完整原body與ORIGINAL receipt只同RAM物件；issuer1095 unique rows×33＝36135 strings，event58列58標的×12＝696 strings（息52／權5／權息1）。ROOT已全列全欄核，capital／payout numeric **NOT VALIDATED**。

| 原件 | issuer：t187ap03_L | event：TWT48U_ALL |
| --- | --- | --- |
| HTTP／body bytes | 200／1327573B | 200／15728B |
| body SHA-256 | `154d8129ab0db28404b93ca46ce8057f71f036d440d1592b53f8dd5fc2048115` | `eaeb52d866a371f7062dd019c38aee13534f024a44fc47d24b7ec3f591533640` |
| ORIGINAL receipt bytes | 6965B | 4463B |
| receipt SHA-256 | `f1685d2091fee1476512263ccc77933bd78fe94c9ad1c1393d39905aa7d467fb` | `eb951717d348df4c5ad265ac9e04b5c00c913dc010facd25dc2feb9f06cf0af6` |
| UTC start | `2026-10-07T23:14:18.052370+00:00` | `2026-10-07T23:11:25.852717+00:00` |
| UTC end | `2026-10-07T23:14:21.119396+00:00` | `2026-10-07T23:11:25.907740+00:00` |
| producer generation | `008f3923-5d9b-4ed3-9bdd-01ed2b613aa8` | `db4041c6-9fc4-42c1-b7cc-91a6ba6a2afc`（外部generation，不是receipt欄位） |

Taipei觀測10/08，選定研究cutoff2026-10-08；本批公司原出表1151007／ISO2026-10-07，不當發布／first availability。1095公司與58事件是本批fresh原件，不重用歷史1094／10TDR或上一62事件snapshot。

### 41.2 同代號原欄位與時間

| Code | 原全名／簡稱 | 原上市日／ISO | 原industry | issuer／event ordinal |
| --- | --- | --- | --- | --- |
| 1449 | 佳和實業股份有限公司／佳和 | 19920506／1992-05-06 | 04 | 78／46 |
| 1463 | 強盛新投資控股股份有限公司／強盛新 | 19961205／1996-12-05 | 04 | 88／47 |
| 2614 | 東森國際股份有限公司／東森 | 19950923／1995-09-23 | 20 | 440／51 |

公司Code exact join eventCode；issuer全名／簡稱與eventName分列，三股eventName本次各exact等於原簡稱；事件Name若不等任一公司原名即unavailable，duplicate／conflict拒用、不silent overwrite／fallback。出表ROC7、上市Gregorian8或ROC7 strict有效，raw與ISO保留；report／listing／Taipei observed／cutoff／effective event日分離，published／first availability／revision仍unknown、nonPIT。行業只原04／20，不證產業名稱／分類品質／ordinary／0056ETF／fullmarket／price／capital數值；0056issuer不支持，不由此判斷security類型。

### 41.3 已接受與釋放邊界

20 actual TestClient calls含8invalid issuerPOST先422／sourceGET0／DB0、三股positive／cachedPOST、missing-cutoff／07／0056unavailable、1463權10/15事件available真零（全feed58／range2／kind0／items[]）及1449恢復08；可信desktop／narrow三股／trace／返回／502清值見個股頁§46。ROOT inspector rows-vs-items KeyError原失敗保留；修正tail未重複調來源或API，再獨立核全原件通過，不冒稱來源gate失敗。

API26328正常STOP raw0實際印server_stoppedtrue／issuer_source_gets1／event_source_gets1／四audit0；完整原件隨API釋放，不restart／replay／clone／hydrate／preload。兩preview只RAM rebuild、無重啟API／新GET，五PID absent／8805、8806無listen／onlyownedpage關閉／tabs[]、test／product／artifactfiles0B／privateIO0已ROOT接受，shared indexcache另報，驗證及正常SIGINT raw1收據見[開發入口](development-baseline/README.md)。

本批coreoperation+1／standalone coredependency0／reliability0／stall0→0；metadata／DOC不計依賴解除，完整M1／M2／M3未完成。SOURCE13＋DOC6待review／freeze／索引／commit／另准merge，下一產業trace與finite新quota未准入，詳[執行清單](ROADMAP_EXECUTION.md)；正式DB／採購／外部帳戶／交易未授，完整原始收據留ROOT原task。

## 42. M1-TWSE-ISSUER-INDUSTRY-TRACE-20261008-1/B1：兩碼引用與同截止原件

2026-10-08。ROOT已有限接受SOURCE12、兩完整TWSE碼名有來源引用本地研究、兩fresh金融原件、21 direct API與可信desktop／narrow全矩陣及實際停止後failure clear。本批coreoperation+1／standalone coredependency0／reliability0／stall0→0，不外推完整M1／M2／M3。分類語意見[產業 §10](INDUSTRY_CLASSIFICATION.md)，操作及待驗見[個股頁 §47](STOCK_RESEARCH_PAGE.md)，驗證入口見[開發入口](development-baseline/README.md)。

### 42.1 官方引用與用途

| 官方證據 | 本輪核對內容／日期角色 |
| --- | --- |
| [TWSE B.12.00](https://www.twse.com.tw/staticFiles/product/broker/ff80808166388ea1016676ac941001e0.pdf) | 附錄三完整 `04＝紡織纖維`、`20＝其他`；printed p92／zero-based p100／parsed104頁。107/10修訂、109/03實施，分別2018-10／2020-03，保留month precision。 |
| [2023產業格式公告](https://eshop.twse.com.tw/zh/news/detail/0000000087e9b84901886b8d96940024) | published2023-05-30、patch effective2023-07-03；16更名及35–38新增作版本脈絡，不代公司分類生效。 |
| [FL007104第2條](https://twse-regulation.twse.com.tw/TW/law/DAT0201_print.aspx?FLCODE=FL007104) | 修正2025-06-09；33名稱清單仍含兩完整名稱，並非本輪完整code表或2026完整current證明。 |

以上是ROOT核對的 `parsed_official_document`，沒有原始文件body／ORIGINAL receipt SHA，不能捏造PDF／公告／規則raw傳輸雜湊。依[TWSE使用條款](https://www.twse.com.tw/zh/terms/use.html) §8，ROOT本輪限縮解釋僅准兩條完整碼名的本地研究引用，條件為identify_source及preserve_complete_name_integrity；不將政府issuer資料OGL移轉為整碼表OGL，不准完整表重發布或原文件下載／保存。此引用不證完整current taxonomy、ordinary／ETF身分、membership、公司分類effective／PIT或策略。

新[引用registry](../backend/worker/twse_industry_registry.json)：`twse-industry-citation-r1-2026-10-08.1`／profile `twse_two_code_complete_name_local_citation`，external registry digest `sha256:75b7667f65a9da7397a72a1e9c494a35364f7563faedc4df2cda21f12e61b647`；consumer `twse-issuer-industry-trace/m1-v1`／policy digest `sha256:e9815a28d0ec22d29cd82c5524b02612debff4fec0110465002f6016afbae9b8`。引用宣告version `twse-two-code-citations/b12-notice-fl007104-2025-06-09-v1`／canonical ROOT-attested excerpt digest `sha256:dfba7e99fdb9343d71b34361afc04c0198a3ab1ebc31ff8a175fee588aa0fac8`；這些是canonical宣告pin，不是來源文件raw SHA。原四源defaults／pins、issuer v1及§41原契約保持。

新Gov／Swagger actual directRAW均HTTP200，日期為UTC2026-10-08；Gov [dataset18419](https://data.gov.tw/api/v2/rest/dataset/18419)4759B，SHA `a12cfebfba57d5666d12c57f1e094a7802b001359d2c189c5857cb1f6d19b6d9`，00:25:30.156443～00:25:30.388763+00:00，license1／free／33欄；[Swagger](https://openapi.twse.com.tw/v1/swagger.json)309960B，SHA `06e1cea82448361e733a0ad1ae16e52f5d5d6b71905acd078472f852c32c0eb0`，00:25:30.388763～00:25:30.524342+00:00，適用既有33 string schema。bytes／SHA與前版相同仍是本次新actual GET；ROOT extractor假設items造成KeyError raw1保留，未重GET，不改寫extractor成功。其他官方metadata reader只證parsed核對，不推算raw HTTP請求總數。

### 42.2 兩份本輪fresh ORIGINAL

各producer NEW empty distinct generation、ONE exact HTTPS GET／single attempt；FIRST失敗亦SPENT。5MiB／identity／retry0／redirect0／warmup0、per-operation20秒上限（實際timeout15）及30秒cooperative非harddeadline沿issuer／event已准入契約。完整原body＋ORIGINAL receipt停止前在ROOT本程序同RAM held objects逐列獨立核，taxonomy runtime GET0；financial quota2已SPENT，不以body相同重用舊receipt／generation。

| 原件 | issuer：t187ap03_L | event：TWT48U_ALL |
| --- | --- | --- |
| HTTP／body bytes／完整範圍 | 200／1327573B／1095 unique×33＝36135原string | 200／15728B／58列×12＝696原string；52息／5權／1權息 |
| body SHA-256 | `154d8129ab0db28404b93ca46ce8057f71f036d440d1592b53f8dd5fc2048115` | `eaeb52d866a371f7062dd019c38aee13534f024a44fc47d24b7ec3f591533640` |
| ORIGINAL receipt bytes／SHA-256 | 6965B／`5d6c5f2a8219e680ce4b7a04a37d8a74b1314f55b0cce1baabbea2bd9bf37445` | 4463B／`68a7a10c423a64fd84174740d248f20796de1d3d9df7c1203a3006070d4a77f2` |
| UTC start／end | 2026-10-08T00:51:57.321860+00:00／2026-10-08T00:52:04.316732+00:00 | 2026-10-08T00:51:54.752129+00:00／2026-10-08T00:51:57.291640+00:00 |
| producer generation | `b8652dd0-db12-4662-bf2b-e1e8ea21dbfc` | `19c0d5cb-ee45-4a48-baed-1819c56db1fa`（外部generation，非receipt欄） |

ROOT核完整schema／maps／dates／ordinals／dualSHA；新body SHA與§41相同，但本次fresh GET／receipt／generation不同。selected1449／1463／2614 raw04／04／20精確引用紡織纖維／紡織纖維／其他；公司六原欄、原Code／Name exact join與report1151007／listing日期保持，capital／issuedshares／payout numeric NOT VALIDATED。Taipei觀測及metadata觀測2026-10-08／研究cutoff2026-10-08；publication／firstavailability／revision與公司分類生效仍unknown／nonPIT。

### 42.3 已接受與釋放邊界

21 direct API checks已ROOT接受：FIRST前8 invalid422／sourceGET0／DB0；三真公司同cutoff碼名及完整issuer／event dualSHA，三cachedPOST／missing／earlier07／0056 unavailable、08恢復；1463權10/15真零仍total58／range2／kind0／items[]。既有issuer capture明示取得，industry是同資料pure-read投影、不新增producer／外網／DB寫入。

可信desktop1365×900／narrow390×844三股公司六原欄／04、04、20與完整碼名／三事件型、完整引用trace／dualSHA／ordinals／分類effective未知、真零／missing／earlier恢復／原五條件back／nooverflow已接受，詳個股頁§47。API停止後same-key1449 READ實際失敗清headline及三table／provenance、crossselected1463 GET502整頁error與清值均受驗，不作positive。

停止前ROOT另核完整same held originals identity／全schema／1095 unique／58及dualSHA，sourceGET仍各1、所有guards0。API52996正常STOP raw0，實際SHUTDOWN／server_stopped=true／artifact0B；兩ORIGINAL RAM隨process終止釋放，不restart／replay／clone／hydrate。Preview55124／compiler31816正常SIGINT raw1，實際SHUTDOWN GET46／POST7／rejected0、FS／network／subprocess guard0／diskartifact0。三PID absent、8807／8808無listen、唯一ownedpage正常closed／tabs[]已核；new test／productartifactfiles0B／privateIO0／DBfiles0，shared indexcache另報。必要41backend／7warnings與45src noEmit＋71targetchecks raw0；原失敗／ACK未delivery及viewport讀回界線留[開發入口](development-baseline/README.md)／ROOT原task，不改exit。

本批僅兩碼本地引用及三公司具名研究操作；capital／issuedshares／payout numeric、ordinary／0056ETF／完整current taxonomy／membership／排名／歷史price／PIT／策略／Plan／保存未驗。Financial quota2 SPENT、舊originals不可重開或重用；下一具名新核心與新source／時間／保存gate另核，見[執行清單](ROADMAP_EXECUTION.md)。SOURCE12＋DOC7 exact19待ROOT DOC review／freeze／索引／commit／另准merge；正式DB／採購／外部帳戶／交易未授，最終收據留原task。

## 43. M1-CHIPS-STOCK-SCOPE-7-GROSS-TRADE-20-1006-1/B1：七股gross買賣與新來源准入

2026-10-08。ROOT precise grant先於implementation／financialGET，source10及fresh原件／數值／具名操作已有限接受；financial22已SPENT。本節只管理本B1獨立政策與來源／數值契約；已接受§31／37／38、oldprofiles／defaultpins、failed producer及其未跑歷史不改。新操作及完成條件見[個股頁 §48](STOCK_RESEARCH_PAGE.md)／[執行清單](ROADMAP_EXECUTION.md)。

### 43.1 新版本與外部pins

ROOT獨立RAM canonical policy **10654 UTF-8 bytes**，version `m1-chips-gross-trade-stock-scope-7-tpex-2026-10-06.1`，外部digest `sha256:ea02b5f32ff2bd0c415e14192c6daa276dc2781e8a6c2d4e5b90bcad776d1144`；profile及API caller外部EXPECTED_PROFILE皆為 `free_public_local_chips_only_daily_gross_trade_stock_scope_7`。Expected pin不能由received policy自建；不能以oldcapture／shareddefaults代新准入。只有純解析／計算函式可重用，不restart／replay／clone／hydrate／preload舊producer或已釋放originals。

| Identity | 本B1 exact版本 |
| --- | --- |
| worker | `tpex-institutional-gross/chips-stock-scope-7-v1` |
| capture | `tpex-institutional-gross-capture/chips-stock-scope-7-v1` |
| read | `institutional-daily-gross-read/chips-stock-scope-7-v1` |
| calculation | `gross-buy-sell-net-running-sum/window-reset-int64-v1` |
| daily source | `dataset-11856-dated-csv-observed-2026-10-08/chips-gross-trade-stock-scope-7-v1` |
| index source | `dataset-11391-month-csv-observed-2026-10-08/chips-gross-trade-stock-scope-7-v1` |

新canonical未另設calendar_schema／calendar_version key。Calendar identity由本B1 policy version＋digest、新index sourceversion及 `observation_date=2026-10-08` 固定約束；上述read schema涵蓋calendar結構，不沿用oldcalendar版本或自行命名額外常數。Selected為TPEx3105／3293／5274／5347／6488／6510／8069；explicit researchcutoff `2026-10-06`，不提升default日期或其他profiles。

### 43.2 新metadata核對、用途與署名

ROOT新DIRECT首6：REST11391／REST11856、[OGL1.0](https://data.gov.tw/license)、[TPEx條款](https://www.tpex.org.tw/zh-tw/gtsm_disclaimer.html?l=zh-tw)、[交易規則](https://www.tpex.org.tw/zh-tw/mainboard/trading/rules/system.html)及[11503027221公告](https://www.tpex.org.tw/storage/eb_data/11509/11503027221.html)；首metadata抽取未輸出所需terms／rules clauses後，再兩專用extractiondiagnostic GET，合計**8GET／585451B**、HTTP200 identity／redirect0／retry0、只RAM，不能冒稱只有6GET。UTC2026-10-08首6在02:01、兩diagnostic在02:02；完整逐件hash／UTC／原不足留ROOT原task。另兩web reader支援核對OGL與TPEx：OGL成功、TPEx403 InternalError保留且不retry；reader operations不證raw HTTP總量。

[REST11391](https://data.gov.tw/api/v2/rest/dataset/11391)「Index historical data」與[REST11856](https://data.gov.tw/api/v2/rest/dataset/11856)「Information on the trading details of OTC stocks three major institutional investors」，owner櫃買中心／TPEx、license1／free／CSV UTF-8／exactresourceURL已核；body2310B／4205B的SHA留ROOTtask，不代金融原件。

OGL1.0完整署名義務及TPEx條款§7政府資料開放例外已ROOT核，§5並未全局取消；僅准本B1 `local_fetch/raw_store/summarize`，raw_store限processRAM，summarize限gross買／賣／net本地研究。完整署名保留owner／year2026／上述兩完整dataset名／observedversions／OGL1.0 URL，保留原件完整性。Metadata發布／修改時間不代金融row發布；published／firstavailability／revisionunknown，nonPIT／historical PIT unsupported，不授權磁碟保存／正式DB／採購／帳戶／交易或任意自動抓取。

### 43.3 Finite FIRST與完整originals

新grant為ONE NEW empty producer，由ROOT先核APIempty後native trustedFIRST一次，程序不得probeGET／seed。先2index exact [inx](https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?response=data)，`date=2026/09/01`及`2026/10/01`；驗日曆後採last20，才取exact [dated daily](https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data)的calendar-derived `d=115/MM/DD`，9/07～10/06。最多2＋20＝22GET，1attempt失敗亦SPENT；redirect／retry／warmup0。FIRST_once及cached409，切股／套用／back／heldREAD不得另fetch。准入時financial0；本次trustedFIRST已完成22／SPENT，完整actual原件見§43.5，不重開或重試。

15s每request／180s batch在response及chunk邊界cooperative檢查，非OS硬deadline；收到header後16KiB檢查，非socket硬cap。Index1MiB／daily2MiB／total42MiB；retained64MiB為deduplicated getsizeof estimate，非RSS／peak，診斷16MiB。ALL22 ORIGINAL body及未增補的canonical receipts只RAM，bodySHA／ORIGINALreceiptSHA／exactURL／method／HTTP identity／UTC／generation須由ROOT在same held objects獨立核；不得用augmented provenance重造receipt或以相同bodySHA冒freshoriginal。0privateIO／priceGET／DB／productartifacts，保存／跨程序未授。

### 43.4 全日曆、ALL25原欄與gross計算

不硬沿舊25rows。兩月**全部返回**原6欄先驗日期／unique／requested month／weekday／nonclosed／≤observation10-08／finite positiveOHLC及上下界；postcutoff合法原列完整保留追溯而不採，不假定25或26列，不從缺列推休市。採≤10/06的完整24weekday正面集合扣公告9/25、9/28，與§31 required24相符；last20為9/07～10/06，last5為9/30、10/1、10/2、10/5、10/6。完整calendar不代ordinary stock20／21closes或MA20。

Daily全部來源列先驗25string、日期／code唯一及非空name；ALL7×20＝140selected rows的3500原strings／3080金融int64與七組買−賣＝net、外資／dealercomponents及total關係全驗，不能只驗目前所選股或外推其他股金融coverage。Selected investor原欄以0-based索引：foreign買／賣／net＝3／4／5（不含外資自營商）、trust＝12／13／14、dealer＝21／22／23（自行＋避險總）；驗components不換foreign口徑。

Canonical單位股，integer string傳遞；gross買／賣為非負int64，net為signed int64，張精確÷1000、既有單位公式不改。每日、buy／sell／net三種running prefix與ALL84gross＋42net window totals均須exact計算且在int64範圍：0～9223372036854775807（gross）／−9223372036854775808～9223372036854775807（net）；期末prefix與獨立window sum對帳，buy−sell＝net。每一5／20窗口buy／sell／net均從第一日前0起算，5不延用20prefix。任一daily／prefix／total、完整性／pins／來源關係不合使whole7profile failclosed，unknown／missing不補0或縮窗。

每point-date-row保ALL25原string／原ordinal／bodySHA／ORIGINALreceiptSHA及全部calendar原列。fresh有gross0cell且ALL7完整gate成立才可驗actualzero，fixture不代真值；本次27每日gross0cells已核，ALL84窗口gross totals均非0，不稱actual零窗口。新每日gross／累計／net對照及返回有限接受，old daily net不重計；coreoperation+1／standalonecoredependency0／reliability0／stall0→0，完整M1／M2／M3未完成。

### 43.5 本次完整actual與釋放邊界

NEWgen `7a69c0e8-a019-41c6-9a24-d0b7e2833b3b` nativeFIRST_once完成22financialHTTP200identity、body2907155B／ORIGINALreceipts23319B，UTC2026-10-08T02:27:08.158379～02:27:18.782558+00:00。ROOT獨立核FULL22 heldbody＋未增補canonical receipts／dualSHA／UTC／exactURL、full18098dailyrows、ALL140×25strings／3080int64／components及total關係；calendar25returned→24採≤10/06→last20／5，postcutoff10/07原6欄保留不採。全部42windows84gross＋42nettotals、525points1575prefixcomponents精確獨立對帳；停止前sameheld ORIGINAL body＋receipt equality再核raw0。完整逐件hash／數值表留ROOT原task，不另建附件或重造receipt。

Actual每日gross0共27cells，desktop3105／trust／9/18sell0與narrow5274／trust／9/30buy0均有ALL25trace；84窗口gross totals全非0。完整可信UI／API／mask／failureclear沿PAGE48。Metadata8direct＋2webreader及financial22已SPENT，reader403保留；原件隨API正常SIGINT／SHUTDOWNtrue raw1釋放、guards0／source_requests22 producer22，無restart／replay／hydrate。test／productartifacts0files0B、privateIO／DB／priceGET0；完整退出／錯誤／命令見[開發入口](development-baseline/README.md)。Source10＋DOC6版本封存待ROOTreview／freeze／索引／commit／另准merge；不以索引或Git代功能驗收。
## 44. M1-CHIPS-STOCK-SCOPE-7-DIRECTION-SEGMENTS-20-1006-20261008-1/B1：七股方向、計數與窗口區段

2026-10-08。ROOT已有限接受新來源／數值與具名操作，financial22及metadata已SPENT。本節只管理新namespace；oldnet／oldgross／defaultpins與四TWSE profiles不改。操作見[個股頁 §49](STOCK_RESEARCH_PAGE.md)，入口見[開發入口](development-baseline/README.md)。

### 44.1 獨立版本與外部pins

ROOT canonical12382 UTF-8 bytes，version `m1-chips-direction-segments-stock-scope-7-tpex-2026-10-06.1`，外部SHA `eb7a4dd688907855dd91250bfbec96b4dd8b2cb65085dce49e7e12c3a80c5348`，profile `free_public_local_chips_only_direction_segments_stock_scope_7`。本根新worker原文已唯讀核對canonical bytes／SHA及下列identity；expectedpins由ROOT外部提供，不從receivedpolicy自建。

| Identity | 本B1 exact版本 |
| --- | --- |
| worker | `tpex-institutional-direction/chips-stock-scope-7-v1` |
| capture | `tpex-institutional-direction-capture/chips-stock-scope-7-v1` |
| read | `institutional-direction-segments-read/chips-stock-scope-7-v1` |
| calculation | `net-sign-triples-counts-contiguous-segments/window-limited-int64-v1` |
| calendar schema | `institutional-direction-calendar/chips-stock-scope-7-v1` |
| calendar／index version | `dataset-11391-month-csv-observed-2026-10-08/chips-direction-segments-stock-scope-7-v1` |
| daily version | `dataset-11856-dated-csv-observed-2026-10-08/chips-direction-segments-stock-scope-7-v1` |

本B1新設calendar_schema／calendar_version，不回改§43無此key的gross契約。TPEx3105／3293／5274／5347／6488／6510／8069、explicit cutoff2026-10-06／observed2026-10-08；不提升default日期或profiles。

### 44.2 Metadata、用途與原件限制

新8direct共581122B／HTTP200 identity／redirect、retry0，另2webreader：OGL成功、TPEx403 InternalError不retry；reader不證rawHTTP總量。首6共542891B，stdout HTML截斷且ord3／4 ORIGINAL receipts未保存，不能聲稱8件完整receipts。另terms13535B＋rules24696B＝38231B的兩專用診斷完整clauses已ROOT核；原不足留task；8direct SPENT，不補舊receipts／不再GET。

[REST11391](https://data.gov.tw/api/v2/rest/dataset/11391)／[REST11856](https://data.gov.tw/api/v2/rest/dataset/11856)已核ownerTPEx、license1、free、CSV UTF-8。[OGL1.0](https://data.gov.tw/license)完整署名義務、[TPEx條款](https://www.tpex.org.tw/zh-tw/gtsm_disclaimer.html?l=zh-tw)§7政府資料開放例外及§5非全局取消已核。僅授本地RAM方向用途。完整canonical署名逐字如下：

> 財團法人中華民國證券櫃檯買賣中心（Taipei Exchange, TPEx）[2026] 櫃買指數歷史資料（dataset11391；dataset-11391-month-csv-observed-2026-10-08/chips-direction-segments-stock-scope-7-v1）及上櫃股票三大法人買賣明細資訊（dataset11856；dataset-11856-dated-csv-observed-2026-10-08/chips-direction-segments-stock-scope-7-v1）。此開放資料依政府資料開放授權條款（Open Government Data License）進行公眾釋出，使用者於遵守本條款各項規定之前提下，得利用之。政府資料開放授權條款－第1版：https://data.gov.tw/license。原欄、來源及完整性保留；方向與區段為本地衍生結果。

Published／firstavailability／revision未知、nonPIT，metadata時間不代金融row發布或決策時可知；磁碟保存／跨程序／正式DB／交易未授。

### 44.3 Finite FIRST及完整日曆

ONE NEW empty distinct producer，無seed／preload；trustedFIRST_once先2index月CSV，再完整calendar驗證後last20的20daily，總22GET，失敗亦SPENT；retry／redirect／probe／warmup0。只RAM保存ALL22 ORIGINAL bodies及未增補canonical receipts；ROOT同heldobjects獨立核完整identity／exactURL／UTC／dualSHA，不重造receipt、重開producer或重用舊capture。切股／套用／back／heldREAD不另fetch，cachedcapture409。

新policy15s/request、180s/batch為request／response／chunk邊界cooperative檢查；16KiB header為收到後postcheck，非socket硬cap。Index1MiB／daily2MiB／total42MiB；retained64MiB為deduplicated getsizeof estimate，非RSS／建構peak；diagnostic16MiB。原件／產物／privateIO／DB／priceGET均受本B1有限gate約束。

全部返回calendar原6欄先驗unique日期／requested month／weekday／nonclosed／≤observation／finite positiveOHLC及上下界，再與採入完整weekday集合扣[9/25、9/28公告](https://www.tpex.org.tw/storage/eb_data/11509/11503027221.html)對帳；不硬定returned25或從缺列推休市。合法postcutoff原列保留追溯但不採。此次25returned→24adopted→last20為9/07～10/06，last5為9/30、10/1、10/2、10/5、10/6；10/7保原欄excluded。Index calendar不代ordinary closes／MA20。

### 44.4 原欄、分類、counts與segments

全部daily來源列先驗25strings／日期／code唯一／非空name；ALL140selected的3500strings／3080金融int64及買−賣、components／total關係完整核。Foreign原net欄5不含外資自營商、trust14、dealer23為自行＋避險總（0-based）；原signed int64 canonical股數與精確股／張公式不改，unknown／missing不補0。

三net符號五類互斥且涵蓋27signcases：`all_positive`三正、`all_negative`三負、`opposite`至少一正一負且可含零、`single_direction_with_zero`單一非零方向且含零、`all_zero`三個精確零。每investor×5／20窗口正負零counts總和＝窗口長度；segments按窗口交易日期順序為maximal同sign連續區段，完整覆蓋一次、無重疊／缺口／相鄰同sign，zero獨立且終止正負run。Latest run僅最後一段，首段earlier_unknown=true，不以較長窗口或完整歷史外推更早日數。任一來源／pins／結構／數值／分類／區段不合，whole7profile failclosed，不縮窗或跳壞股。

Segment-date展開三原net、ALL25原strings／header／ordinal／bodySHA／ORIGINALreceiptSHA及完整calendar。Actualzero只由fresh原net精確0證明；derived count=0須逐原列predicate核，fixture不補實件。

### 44.5 本次actual與已知缺口

NEWgen `819af242-616e-4e28-8302-87b0062a2ecc`，唯一trustedFIRST22 HTTP200 identity，body2907155B／完整ORIGINAL canonical receipts23737B，UTC2026-10-08T05:16:30.625464～05:16:42.788936+00。ROOT同RAM independent stdlibCSV／日期／components／identity／fullschema／dualSHA／URL／UTC／int64及safeintMath核full18098rows、ALL140與完整API graph；API234695B canonicalSHA `048f72ea5fe7a8ccd318dc92916dcc9d39a32a9f437ecff1a5051b930591ce8d`。42groups／258segments／latest42、count0 predicates44已逐列對帳；140triples為99opposite／23allpositive／17allnegative／1singlewithzero／allzero0。

Fresh每日net零2格：8069trust9/23、3293trust9/29，各為獨立1day zero run。44個統計count0不代表44個每日net零。Actual all-zero triple／整窗zero run／latestzero無實件，保留驗收缺口，不以fixture聲稱通過。完整UI／API／清值邊界沿PAGE49。

停止前ROOT再核FULL22 sameheld bodies＋ORIGINAL receipts逐byteequal與全API graph raw0；financial22仍SPENT，原件正常退出後釋放，不restart／replay／clone／hydrate／preload。Test／productartifacts0files0B／privateIO0／DB0／ordinarypriceGET0；命令、guards、原失敗及清理見開發入口。

## 45. M1-CHIPS-STOCK-SCOPE-7-ADJACENT-WINDOWS-5-1006-20261008-1/B1：兩相鄰5日比較與新來源准入

2026-10-08。ROOT有限接受SOURCE9、新來源／數值與具名比較操作；本節只管理新namespace，old series／gross／direction／defaultpins及四TWSE profiles immutable。操作見[個股頁 §50](STOCK_RESEARCH_PAGE.md)，驗證入口見[開發入口](development-baseline/README.md)。

### 45.1 獨立版本與外部pins

本worker canonical9284 UTF-8 bytes，version `m1-chips-adjacent-windows-stock-scope-7-tpex-2026-10-06.1`，ROOT外部SHA `092f86d7fd2797b88f12f92e0474beb120139143ba5c3f3e27edb0c52f5c235e`，profile `free_public_local_chips_only_adjacent_windows_stock_scope_7`；本根literal已唯讀核bytes／SHA／685B署名。Worker／capture／read及consumer必須完整匹配外部expectedpins，不能從receivedpolicy自建pin或提升old defaults。

| Identity | 本B1 exact版本 |
| --- | --- |
| worker | `tpex-institutional-adjacent/chips-stock-scope-7-v1` |
| capture | `tpex-institutional-adjacent-capture/chips-stock-scope-7-v1` |
| read | `institutional-adjacent-windows-read/chips-stock-scope-7-v1` |
| calculation | `adjacent-five-session-counts-net-pairs-deltas/window-limited-int64-v1` |
| calendar schema | `institutional-adjacent-calendar/chips-stock-scope-7-v1` |
| calendar／index version | `dataset-11391-month-csv-observed-2026-10-08/chips-adjacent-windows-stock-scope-7-v1` |
| daily version | `dataset-11856-dated-csv-observed-2026-10-08/chips-adjacent-windows-stock-scope-7-v1` |

TPEx3105／3293／5274／5347／6488／6510／8069、explicit cutoff2026-10-06、observed2026-10-08，foreign／trust／dealer、兩個各5交易日窗口；本namespace不提升舊日期或來源。

### 45.2 本輪metadata、用途與完整署名

ROOT NEW6direct HTTP200 identity共545489B／完整ORIGINAL canonical receipts3145B，UTC2026-10-08T07:35:07.686030～07:35:13.984924+00:00；全body／receipt同RAM逐byte／hash及clauses已核後釋放。另2webreader：OGL成功、TPEx InternalError失敗不retry；沒有新reader rawHTTP403證據。6direct＋2reader均SPENT，不冒前輪8件完整receipts或補舊receipt。

[REST11391](https://data.gov.tw/api/v2/rest/dataset/11391)／[REST11856](https://data.gov.tw/api/v2/rest/dataset/11856)之ownerTPEx／license1／free／CSV UTF-8／exact resource及header已核；[OGL1.0](https://data.gov.tw/license)完整署名義務、[TPEx條款](https://www.tpex.org.tw/zh-tw/gtsm_disclaimer.html?l=zh-tw)§7政府開放資料例外及§5非全域取消已核，只授有限local RAM comparison、nondurable用途。685 UTF-8 bytes canonical署名逐字如下，不沿用舊686B：

> 財團法人中華民國證券櫃檯買賣中心（Taipei Exchange, TPEx）[2026] 櫃買指數歷史資料（dataset11391；dataset-11391-month-csv-observed-2026-10-08/chips-adjacent-windows-stock-scope-7-v1）及上櫃股票三大法人買賣明細資訊（dataset11856；dataset-11856-dated-csv-observed-2026-10-08/chips-adjacent-windows-stock-scope-7-v1）。此開放資料依政府資料開放授權條款（Open Government Data License）進行公眾釋出，使用者於遵守本條款各項規定之前提下，得利用之。政府資料開放授權條款－第1版：https://data.gov.tw/license。原欄、來源及完整性保留；相鄰窗口比較為本地衍生結果。

Observation10/08不代金融列發布或10/06決策時可知；published／firstavailability／revision未知、nonPIT。磁碟保存／跨程序／正式DB／交易未授，MIT軟體license不代dataRights。

### 45.3 Finite FIRST與完整日曆

ONE NEW empty distinct generation，seed0／preload=false，trusted FIRST_once先2index再全部calendar驗證後動態10daily，總12GET；失敗亦SPENT，retry／redirect／probe／warmup0。只RAM保存ALL12 ORIGINAL bodies及未增補canonical receipts，producer持有原件與ROOT auditor RAM原件逐byteequal、逐件核exact URL／UTC／identity／dualSHA；不能重造receipt、重開producer或reuse released capture。Apply／切股／back／held READ不新增來源，cachedcapture409。

Policy15s/request／180s/batch僅request-response-chunk邊界cooperative檢查；16KiB header為收到後postcheck，非socket硬cap。Index1MiB／daily2MiB／aggregate22MiB；retained64MiB為deduplicated getsizeof estimate，非RSS或建構peak；diagnostic16MiB。原件、privateIO／DB／ordinaryprice GET及落盤產物受本B1有限gate約束。

全returnedcalendar每列原6欄先驗unique日期／requested month／weekday／nonclosed／≤observation、finite positive OHLC及上下界，再與完整weekday集合扣[9/25、9/28休市公告](https://www.tpex.org.tw/storage/eb_data/11509/11503027221.html)對帳；[交易規則](https://www.tpex.org.tw/zh-tw/mainboard/trading/rules/system.html)只支持本輪已核weekday條件。不硬25rows或從缺列推休市；合法postcutoff列保原件但不採。此批26returned→≤10/06 exact24adopted→last10 split5／5：前5為9/21、9/22、9/23、9/24、9/29，近5為9/30、10/1、10/2、10/5、10/6；10/7及10/8保原欄excluded。Index calendar不代ordinary closes／MA20。

### 45.4 原欄、窗口及positional pair計算

全部daily來源列先驗25strings／日期／code唯一／非空name；ALL7×10=70selected、1750原strings／1540金融int64及ALL22欄buy-sell-net、foreign／dealer components／total關係全驗，才可available。Foreign原net5不含外資自營商、trust14、dealer23為自行＋避險總（0-based）；canonical signedint64股數及精確股／張規則沿既有契約，本輪每個加減／窗口sum步／pair與total delta步均檢overflow。

每investor各5窗positive／negative／zero predicates互斥，counts總和=5；兩窗net各為五原net之和，count delta及net delta均為近5減前5。Maximal同sign連續segments完整覆蓋各窗一次、無gap／overlap／相鄰同sign；zero獨立且終止正負run。Latest僅各窗末段，首段earlier_unknown=true，不外推完整歷史。

每股5 positional pairs依前窗第1～5日配近窗第1～5日，兩個不同日期而非同日比較。Each pair delta=recent原net−previous原net，五pair delta之和=window net delta；每股三investor共21net deltas／63count deltas，35pairs×3=105pair deltas精確核。每pair保兩列ALL25原strings／header／ordinal／bodySHA＋ORIGINALreceiptSHA／三net及全returnedcalendar。Daily net0、統計count0、窗口sum0、delta0各有不同predicate，不把missing或unknown當0；任一來源／pins／calendar／結構／數值／pair conflict，whole7 failclosed，不跳壞股或縮窗。

### 45.5 本次actual及未驗邊界

NEWgen `e9a265f3-4fbd-44c6-a81f-0d76c10cc7b9`，唯一trusted native FIRST12 HTTP200 identity、body1459857B／ORIGINAL canonical receipts12823B，UTC2026-10-08T08:48:54.698286～08:49:06.502104+00:00。ROOT同RAM全12body／未增補receiptbytes／base64、stdlib CSV／Decimal／dates／ALL22selected numeric／components／identity／dualSHA及完整APIgraph核；fullDaily9088rows、selected70×25strings與1540int64。42windowgroups／126counts／125maximal segments／latest42、21delta／63countDelta／105pairDelta及26calendar精確對帳，停前共3次full ORIGINAL／math再核，無額外GET。

Fresh每日net0只有3293trust9/29、8069trust9/23，皆1day zero segment；前窗3293trust latestzero1day／earlier_unknown=false為新actual正面路徑，兩尺寸native受驗。Actual allzero triple／整窗全零／net sum0／total delta0／pair delta0均無實件，缺口保留，fixture不充真值。完整actual API／兩viewport／清值見PAGE50，canonical API133856B、SHA `5fe1d272fdecfdfaf4e9778683e80466b38097779ccae94d6026261bf1bdf515`，完整逐件receipt及數值留ROOT原task。

Financial12／metadata6direct＋2reader SPENT；ORIGINAL RAM已隨正常退出及auditor release釋放，不restart／replay／clone／hydrate／preload。Test／productartifacts0files0B、privateIO／DB／ordinaryprice GET0；不外推price／ranking／filter／Signal／Plan／完整M1，保存／跨程序未授。

## 46. M1-CHIPS-STOCK-SCOPE-7-DEALER-COMPONENTS-5-1006-20261008-1/B1：自行買賣、避險與合計來源及對帳

2026-10-08。ROOT有限接受SOURCE9及具名actual對帳，操作見[個股頁 §51](STOCK_RESEARCH_PAGE.md)，驗證入口見[開發入口](development-baseline/README.md)。本節只管理新namespace，old series／gross／direction／adjacent／defaultpins與四TWSE profiles immutable。

### 46.1 獨立版本與外部pins

本worker exact literal canonical9245 UTF-8 bytes，version `m1-chips-dealer-components-stock-scope-7-tpex-2026-10-06.1`、ROOT外部SHA `54347a73a5d725e702599eb582e9c75550f2c24c6839afd61c890e37bed99eab`，profile `free_public_local_chips_only_dealer_components_stock_scope_7`；本根AST唯讀核bytes／SHA及署名774B，不import或重跑產品。Worker／capture／read／consumer須完整匹配外部expected pins，不能從receivedpolicy自建pin或提升olddefaults。

| Identity | 本B1 exact版本 |
| --- | --- |
| worker | `tpex-institutional-dealer-components/chips-stock-scope-7-v1` |
| capture | `tpex-institutional-dealer-components-capture/chips-stock-scope-7-v1` |
| read | `institutional-dealer-components-read/chips-stock-scope-7-v1` |
| calculation | `dealer-self-hedge-total-buy-sell-net/five-session-step-int64-v1` |
| calendar schema | `institutional-dealer-components-calendar/chips-stock-scope-7-v1` |
| calendar／index version | `dataset-11391-month-csv-observed-2026-10-08/chips-dealer-components-stock-scope-7-v1` |
| daily version | `dataset-11856-dated-csv-observed-2026-10-08/chips-dealer-components-stock-scope-7-v1` |

TPEx3105／3293／5274／5347／6488／6510／8069，explicit cutoff2026-10-06、observation2026-10-08，dealer only／horizon5 only；self／hedge／total三組始終並列，不將old TOTAL改名冒新增操作。

### 46.2 Metadata准入、用途與完整署名

首6 direct metadata HTTP200、body542891B，但holder stdin EOF／正常raw0退出，在全部ROOT transfer前原RAM釋放；6均SPENT、gate未過，不稱完整新規則audit或來源failure、不retry。另2reader一次：OGL完整primary clauses成功，Chinese TPEx InternalError／rendered403；此不是native HTTP counter，兩reader均SPENT。

正面新路徑為NEW3 direct官方[dataset11391](https://data.gov.tw/dataset/11391)／[dataset11856](https://data.gov.tw/dataset/11856) HTML及TPEx English terms，共1061024B ORIGINAL bodies／3813B未增補canonical receipts，UTC2026-10-08T10:33:43.323647～10:33:44.968013+00:00。ROOT完整originals／receipts同RAM逐byteequal／dualSHA及獨立完整HTMLclauses已核；provider金融監督管理委員會證券期貨局（FSC SFB）、ownerTPEx、free CSV／license1／exact resource links、OGL1完整notice及TPEx English §7政府開放資料例外／§5一般下載限制均保留。只有有限local RAM dealer-components比較用途；source45已接受的weekday／9/25、9/28 closure完整規則clauses沿用，不沿用舊financialcalendar或capture，也不將首6重稱完整新audit。

| NEW完整metadata | Body bytes／SHA256 | Original receipt bytes／SHA256 |
| --- | --- | --- |
| 官方11391 HTML | 520853／`6850cab3474a6277c4aedc34c6d30e04bfaffd45fb36017f0caccb6844e358b6` | 1238／`e37f0b8f07f53808d18741cbcdf9cfcb08e323e70536ee82498fd9bb09030f39` |
| 官方11856 HTML | 526582／`b78bd658d22af66fc2d77509ad409195cd6cf8f561e8a495a783dad03dc869c8` | 1239／`b53cf73e050578dca50c66df9a37c61febf02ff728dabd8c8d331d9ccf48d7f1` |
| TPEx English terms | 13589／`f6d74dbad4cdbd40c8f4f4171fa4ed032eb2e6af0e7bd08739e14bbf5152f565` | 1336／`14774d2082f7c9525396dc5e887cbb9c37219c419ecfbccdaac1d965dc90e6b6` |

本worker774 UTF-8 bytes完整署名逐字如下（不是前批685B或mojibake候選）：

> 金融監督管理委員會證券期貨局提供、財團法人中華民國證券櫃檯買賣中心（Taipei Exchange, TPEx）[2026] 櫃買指數歷史資料（dataset11391；dataset-11391-month-csv-observed-2026-10-08/chips-dealer-components-stock-scope-7-v1）及上櫃股票三大法人買賣明細資訊（dataset11856；dataset-11856-dated-csv-observed-2026-10-08/chips-dealer-components-stock-scope-7-v1）。此開放資料依政府資料開放授權條款（Open Government Data License）進行公眾釋出，使用者於遵守本條款各項規定之前提下，得利用之。政府資料開放授權條款－第1版：https://data.gov.tw/license。原欄、來源及完整性保留；自行買賣、避險及總額之每日與五日比較為本地衍生結果。

Metadata觀測不代金融列publication／firstavailability／revision，三者仍unknown、nonPIT；統計依原成交、未含券商帳戶更正。磁碟保存／跨程序／正式DB／交易未授，MIT軟體license不代dataRights。ROOT AST stdout mojibake9472B／ca6d93…候選於任何source／finance grant前撤回，正確ASCII JSON讀回9245B才核定；原fail留task，不沿用錯pins。

### 46.3 Finite FIRST與全calendar

ONE NEW empty distinct producer，seed0／preload=false；明示trusted FIRST_once先2index，全部returnedcalendar原6欄先驗requested month／unique日期／weekday／nonclosed／≤observation、finite positive OHLC與上下界及finite漲跌，再將≤cutoff採入日期與完整weekday扣已核9/25、9/28休市對帳，才fresh derive last5、動態5daily。失敗亦SPENT；retry／redirect／probe／warmup／preload0，不硬26或舊dates。合法postcutoff保原列excluded；index calendar不代ordinary closes。

Exact GET sequence：本新index base URL `https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?response=data`，加percent-encoded Gregorian `date=2026/09/01`及`2026/10/01`；再新daily base URL `https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data`加各derived日期percent-encoded ROC `d`。Body空、HTTP200／identity／UTF-8 CSV，完整ALL7 ORIGINAL bodies及未增補canonical receipts只RAM，同RAM producer與ROOT auditor原bytes逐byteequal、逐件URL／UTC／dualSHA；不以receipt重造或released capture作seed。

Max7requests／12MiB aggregate／1MiB index／2MiB daily；retained64MiB為deduplicated getsizeof estimate，非RSS／建構peak；diagnostic16MiB。15s/request／180s/batch只cooperative request-response-chunk檢查，非OS硬deadline；16KiB headers為received postcheck，非socket cap。

### 46.4 ALL25原欄與每日／窗口計算

全部daily先驗25原strings／date／code唯一／name及ALL7 identity／missing，selected35×25=875strings、35×22=770金融int64全部合格後才available。Canonical signed-int64股數、gross非負、每buy−sell=net，ALL22／七buy-sell-net triplets／foreign components／dealer components／三法人合計關係完整核，不只取三組顯示欄。任一來源／pins／calendar／結構／數值／identity conflict則whole7 unavailable，不跳壞股／補0／縮窗。

| Dealer component | 0-based買／賣／淨額 |
| --- | --- |
| 自行買賣 self | 15／16／17 |
| 避險 hedge | 18／19／20 |
| 合計 total | 21／22／23 |

Each day及window，每metric self＋hedge=total、buy−sell=net；三組buy／sell／net各自按本fresh5順序累加，everycomponent addition／subtraction及每sumstep檢signed-int64。股／張精確÷1000、至多3 decimals，不以float或圖形約值對帳。每列保ALL25原strings／header／ordinal／bodySHA／未增補ORIGINALreceiptSHA／URL與9component metrics；全returnedcalendar原欄可追溯。Zero predicates只針對合格原數值，missing／unknown不當0。

### 46.5 本次actual與未驗

NEWgen `edb7ac56-f36f-4fab-bff8-85dc916a2fbb`，唯一trusted FIRST7 HTTP200／identity，body732030B／未增補original receipts7530B，UTC2026-10-08T11:15:02.253776～11:15:05.281361+00:00。ROOT全部7original／receipts、stdlib CSV／Decimal／dates、4557 full daily rows／ALL35×25／770int64／ALL22 components與sumsteps及fullAPI graph完整核，停前再核原bytesequal／math／API；不冒3次fullmath。26 returnedcalendar→≤10/06 exact24 adopted→last5：9/30、10/1、10/2、10/5、10/6；315daily／63window metrics精確對帳。Full API79080B，SHA `0c3ac2b80a65c3bb8bad9225195d18ba3e8d106763e51e4bd9c36bf316465a38`。

Actual零只有5274 self sell 10/5及10/6，兩viewportdaily與原列trace皆核；windowzero／triplezero／netzero缺實件未驗，fixture不補actual。可信FIRST是1277×924，當時未beforeclickassert1365，不聲稱FIRST1365；之後兩viewportALL7及清值見PAGE51。金融7／metadata首6＋2reader＋新3全SPENT；原件與derived RAM已釋放，不restart／replay／clone／hydrate／preload。Product／testartifacts0files0B、privateIO／DB／ordinarypriceGET0；無save／crossprocess／ranking／filter／price／Signal／Plan或完整M1外推。

## 47. #36 qa1／qa2：七股 TPEx 法人六日 dated CSV 與兩截止五日分子（issue36-two-cutoffs-v1）

2026-10-11。#36 以政府 [dataset11856](https://data.gov.tw/dataset/11856) 的 TPEx dated CSV 取得七股六個日期的法人原件，供 2026-10-05、2026-10-06 兩個截止日各含截止日向前五個交易日的三法人淨股數與合計 consumer（產品 `backend/app/tpex_institutional_five_day_source.py`，測試 `backend/tests/test_tpex_institutional_five_day_source.py`）。本節只管理這個新 namespace，不提升也不改寫其他節的 policy、pins、capture 或 default；六個日期由外部 policy 固定、不由日曆推導，本單不取日曆與 metadata（requests 0）。取得過程與 QA 收據保存在 [#36](https://github.com/YiCheng0608/stock-lab/issues/36)，下列為摘要並附留言編號。

### 47.1 版本、外部 pins 與上限

| 項目 | 內容 |
| --- | --- |
| 外部 policy | version `issue36-tpex-institutional-six-days-two-cutoffs-2026-10-10.1`；canonical 7,500 UTF-8 bytes（sorted keys、compact JSON、無尾 LF）；SHA-256 `93d8e746eccbed035d5a79ffbf178b5f89877017c2aea69e6b841d178c1b51a3`。由全局獨立生成並貼於 [#36 留言 6088588415](https://github.com/YiCheng0608/stock-lab/issues/36#issuecomment-6088588415)，產品不能由被測 policy 自建 expected |
| profile／source | profile `free_public_local_ram_institutional_two_cutoffs_v1`；source id `tpex_government_institutional_csv`，version `dataset-11856-dated-csv/issue36-two-cutoffs-v1`；provider 金融監督管理委員會證券期貨局（FSC SFB），owner 財團法人中華民國證券櫃檯買賣中心（TPEx） |
| consumer | `institutional-five-day-net-summary-two-cutoffs-v1`：7 個 getter、14 個 summary（兩截止 × 七股）、42 個類別合計 |
| 標的與日期 | TPEx 3105／3293／5274／5347／6488／6510／8069；2026-09-29、09-30、10-01、10-02、10-05、10-06 |
| 請求 | 固定 6 個 GET：`https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php`，query 依序 `l=zh-tw`、`se=EW`、`t=D`、`o=data`、`d=<民國日期，如 115%2F09%2F29>`；不換 provider、日期或路由 |
| 上限 | 每份 body 1 MiB、aggregate raw 6 MiB、deduplicated retained-roots estimate 32 MiB（estimate 不是 RSS 或 peak）；每 URL 20 s、整批 180 s（cooperative）；identity、credentials／token／cookie／proxy 0、redirect 0、retry 0、每 URL 最多 1 次；首敗即停且 attempted 即 SPENT；只在 RAM |

### 47.2 用途、授權與署名

用途只限免費公開、本地盤後研究與 RAM 取得／驗證／consumer。Policy `uses`：`local_fetch` 只對本單六個請求、須先有 fresh seal；`raw_store` 只在 RAM；`disk_store`、`raw_publish`、`commercial_use` 不准入；`historical_pit` 不支援。統計基準為原成交、未含券商帳戶更正，單位為股。權利依[政府資料開放授權條款第 1 版](https://data.gov.tw/license)與 [TPEx 條款](https://www.tpex.org.tw/zh-tw/gtsm_disclaimer.html?l=zh-tw)：§7 政府開放資料例外成立，§5 一般下載限制保留；完整署名見 [§47.7](#477-完整署名)。

qa1、qa2 各是獨立的一次額度。qa2 是使用者的新授權，不是恢復 qa1，qa1 的 SPENT／NO-RETRY 照舊。授權本身不是 seal，每次 real run 另須全局核發 fresh financial-start seal，並由獨立 QA 執行一次。

| 項目 | qa1 | qa2 |
| --- | --- | --- |
| namespace | `issue36-seven-institutional-five-day-two-cutoffs-v1/qa1` | `issue36-seven-institutional-five-day-two-cutoffs-v1/qa2` |
| source-use 授權 | [留言 6088463678](https://github.com/YiCheng0608/stock-lab/issues/36#issuecomment-6088463678)（使用者明示授權），本文 3,129 B／`56240c60afbd88e906efc493d3cc2597070226ea5e47656b86afc9948e0077b0` | [留言 6110215172](https://github.com/YiCheng0608/stock-lab/issues/36#issuecomment-6110215172)（使用者決策收據），本文 1,859 B／`3c5b61b7f79b7e2c238350b51d5329e81b087ef36204141ff185cbb5626619f1` |
| seal 授權收據 | [留言 6110115119](https://github.com/YiCheng0608/stock-lab/issues/36#issuecomment-6110115119) | [留言 6110484185](https://github.com/YiCheng0608/stock-lab/issues/36#issuecomment-6110484185) |
| seal raw | [留言 6110116577](https://github.com/YiCheng0608/stock-lab/issues/36#issuecomment-6110116577)，6,518 B | [留言 6110485908](https://github.com/YiCheng0608/stock-lab/issues/36#issuecomment-6110485908)，6,518 B |
| seal pin（seal raw 的 SHA-256） | `836c24ca695fced7826c7d3c88a69a138f15697a4fe90cdf8487512910b78c03` | `abe34083c542a08b943bf2fb5e63ed58ebb5ee13006772fdf6d1631fb3251890` |
| seal 有效期（2026-10-11 UTC） | 14:35:16～15:20:16 | 15:16:05～16:01:05 |
| candidate | `bc2ed20fdded519b80c8e99bac0799ea854e7eaf` | `a4d89664e2bf3ce4614169abee181db2ade68a1b` |
| 產品檔 SHA-256 | `80f2340d0931c6a1a5ece879894fe52adb9793ebcb376bfc2f6af3aec0a90308` | `f66620358660cf4455a8535233f8af0cf9b2ca15037d799ddb2a04c0f0e10f06` |
| 測試檔 SHA-256 | `a332dbb8b16070c08b2297f30d13aa77253cdc809a6382efa3627d839019a8f9` | `dd208c159cbe8f2e5b593e0c46f33bf13015757f22e648f717a2977ca66cd421` |
| script SHA-256 | `3116d3f457c26103d27d1d5d369c5b0774efbfb20cee73fc7de2a8a39d14aff8` | `e89dce8564f16dfc5f1a7db0bb0011f96f7975c8840db094e63286bba2526d1e` |
| typed input（core）SHA-256 | `42447b0bb60c708d983c8ae84b0c29d1da23df5acefd50a41927514bb0ff0deb` | `a63f5f1073d21e11fdd91640f1a6a91d04d7aa7b3a2baa5e352e24bdcf61d55c` |
| loader SHA-256 | `74e54f14ce4a15ba99a754f898d74b801c693dd9e5c6105ea7f616e3569c455b`（兩次相同） | 同左 |

### 47.3 原件驗證與五日分子計算

- **取得**：HTTP 200、identity encoding（無 `content-encoding`），完整 EOF 與 raw hash 通過後才 parse；body 恰達上限時須由既有 framing 讀到 EOF 才接受，未知長度達上限則直接拒絕，不做 +1 或 read(0) probe。
- **標頭**：`content-length`、`transfer-encoding`、`content-encoding`、`content-type` 任一重複即 fail-closed，失敗碼 `duplicate_response_header:<小寫標頭名稱>`；其他標頭重複（如 `cache-control`、`vary`、`set-cookie`）接受，結果與無重複相同。診斷與輸出只含標頭名稱與次數，不含值；不送出、不使用、不保存 cookie。
- **CSV**：strict UTF-8、無 BOM、stdlib `csv` strict；25 欄 header 與 policy 逐欄相符；日期為 7 位民國日期且等於請求日；代號符合 `[0-9A-Z]{4,6}` 且唯一、名稱非空。全部回傳列都驗結構，未選列以有界暫存串流處理；七股各取一列，得 42 列、1,050 原字串、924 個金融整數（42 × 22）。
- **整數**：canonical ASCII 整數字串，signed int64（絕對值至多 `9223372036854775807`）；買進與賣出非負，每組買 − 賣 ＝ 淨額；外資及陸資 ＝ 外資（不含外資自營商）＋ 外資自營商；自營商 ＝ 自行買賣 ＋ 避險；三大法人合計 ＝ 外資（不含外資自營商）＋ 投信 ＋ 自營商。
- **窗口與合計**：類別淨額取 0-based 欄位 5（外資及陸資，不含外資自營商）、14（投信）、23（自營商，自行買賣 ＋ 避險），合計取欄位 24；外資自營商不重複計入。窗口含截止日向前五個固定日期：2026-10-05 為 09-29、09-30、10-01、10-02、10-05；2026-10-06 為 09-30、10-01、10-02、10-05、10-06，10-06 的列不進 10-05 窗口。六份原件須全部取得並合格才有結果，不補 0、不縮窗；每個加減步檢 signed int64 界限。結果單位為股，以 canonical 整數字串表示。

### 47.4 qa1：首個 URL 失敗

2026-10-11T14:36:49.996Z～14:36:51.542Z，candidate `bc2ed20f…`，exit 1。第 1 個 URL（2026-09-29）回 HTTP 200，隨後被當時規則 `duplicate_response_header`（任何同名標頭出現第二次即拒絕）拒絕，body 一個 byte 都未讀。2026-09-29 attempted 即 SPENT，其餘 5 個 URL 未嘗試；閘門 connect_ok 1、resolve_ok 1、blocked 0。沒有取得任何可用 body，真實資料證據為零；NO-RETRY，qa1 額度與 seal 已用盡。

當時診斷只有失敗碼、不含標頭名稱。重複的標頭是 `cache-control` 與 `vary`，這是依 [§47.6](#476-qa2成功取得與驗證結果) 的標頭名稱與次數所作的推論，qa1 當時沒有記錄，無法直接驗證。QA 收據：[留言 6110144414](https://github.com/YiCheng0608/stock-lab/issues/36#issuecomment-6110144414)。

### 47.5 修正與重驗（candidate `a4d89664…`）

只拒絕四個身分標頭的重複，失敗碼帶小寫名稱；其他標頭重複接受，診斷只記名稱與次數。相對 `bc2ed20f…`，產品檔 4 個 hunk：`QA_NAMESPACE`／`SOURCE_USE_RECEIPT(_SHA256)` 常數、`IDENTITY_HEADERS`、seal 固定欄位改用常數、`_fetch` 標頭迴圈；其餘約 1,000 行與 `bc2ed20f…` 逐行相同。

[留言 6110457883](https://github.com/YiCheng0608/stock-lab/issues/36#issuecomment-6110457883) 在合成資料、network 0 下重驗：128 個重複標頭案例（四個身分標頭逐一重複皆拒絕且只嘗試到該 URL、該 URL body 零次讀取；非身分標頭重複 × 三種 framing，結果與基線相同）；qa1 的 namespace 與 source-use 收據任一值都被 `seal_scope_conflict` 拒絕；整批 509 案例 0 失敗。

### 47.6 qa2：成功取得與驗證結果

[留言 6110524656](https://github.com/YiCheng0608/stock-lab/issues/36#issuecomment-6110524656)。2026-10-11T15:17:24.251Z～15:17:39.328Z（15.1 s，其中 capture 與 oracle 驗證 14.48 s），exit 0。第一個請求 15:17:24.788455Z，最後一份 capture 15:17:28.308415Z。閘門 connect_ok 6、resolve_ok 6、blocked 0，只連 `www.tpex.org.tw:443`；六個 attempts 皆 spent 且 completed；aggregate raw 878,045 B（單日最大 147,573 B），retained estimate 1,786,051。

| 日期 | 資料列數 | body bytes | body SHA-256 | receipt SHA-256 |
| --- | ---: | ---: | --- | --- |
| 2026-09-29 | 916 | 147,573 | `d23d020b03c9475dfc554a825d35312cceb6f6f833007804be7a209f6847f0d6` | `e9c9d9464e8b127d76a7df0dbd13fcfd2d182b82a33a86984913db734a2cd380` |
| 2026-09-30 | 913 | 144,999 | `b96b163896a776dff217826a24227bab03cccbfe1a5f35d9e51ee66a4cdeea61` | `969ad780135907dc9139f05d5e558495950132b61363d66247e1d89d2b35cc91` |
| 2026-10-01 | 914 | 146,947 | `15bf44c323e7b89adf4ea9a2eec2b611d60f64848fdbb179cba9c9c64f28abac` | `52cc0686c05114b1a8113262bcd6877fb247bd2f45c3d2acdae83771fe0202b9` |
| 2026-10-02 | 910 | 146,377 | `b9d561b30245b394e68d3cba683f0374cecee2c79fab86f00593d5998938fc66` | `bbfb5f1d1c624b392dacce538f290023b5714ae845fdba37ea8aabd46f3c2d5c` |
| 2026-10-05 | 916 | 147,136 | `62c9e80dfe3c6fd1c687baea35eccff95d102fbad0460513a22eb21d2640b1b0` | `9f2b8560f77f981530954844adf16ceec61b5b667ef80ec60e84b3704d3d3350` |
| 2026-10-06 | 904 | 145,013 | `52ab8b1738dda30cda84b7b3e71d3006479e7cd5938b48762f84b928383a150e` | `2e37ea642d03259b55118cb7c6a311420c41b58b7fbf9623c3ad374000d1eb50` |

六日皆 HTTP/1.1 200、chunked、無 `content-encoding`；receipt 為 `native_https`、namespace 為 qa2、`complete_eof` 為 true。六日回應標頭的名稱與次數完全相同，每次 19 個標頭：`cache-control` ×2、`vary` ×3；`connection`、`content-disposition`、`content-security-policy`、`content-type`、`date`、`permissions-policy`、`referrer-policy`、`server`、`set-cookie`、`strict-transport-security`、`transfer-encoding`、`x-content-type-options`、`x-frame-options`、`x-xss-protection` 各 ×1。身分標頭中 `content-type`、`transfer-encoding` 各出現 1 次，`content-length`、`content-encoding` 未出現；重複的只有 `cache-control` 與 `vary`，依新規則接受。回應含 1 個 `set-cookie`，未送出、未使用，值未輸出也未保存。

驗證（獨立 stdlib oracle 以同一份原件在同一段 RAM 重算，不用產品解析函式產生期望值）：

- 七股每日各恰一列，得 42 列、1,050 原字串、924 個金融整數，欄位與恆等式全部合格，沒有壞欄、壞日、缺列或重複。
- 7 個 getter 的六日逐列逐欄（原字串、整數、列序、日期、header、receipt 與 body SHA）全部等於 oracle，`mismatches` 為空。
- 14 個 consumer 的類別淨額、合計、窗口日期與 `source_rows` 全部等於 oracle（`oracle_match` 14 個皆 true）。
- 日類別淨額有 59 個負值與 1 個真零，保留原值；42 個窗口類別和中有 14 個負值，沒有溢位。
- 結束後 state 為 `released`，originals、selected、roots、results 全清，`cleanup_failures` 為空；22 個結果 handle（1 profile、7 getter、14 consumer）全部撤銷；落盤 0 B。pending、failed、expired、released 四種負向由獨立的合成 RAM 邊界另驗（[留言 6110457883](https://github.com/YiCheng0608/stock-lab/issues/36#issuecomment-6110457883)）。

兩個截止日的三類淨股數與合計（本地衍生結果，單位：股，由 [留言 6110524656](https://github.com/YiCheng0608/stock-lab/issues/36#issuecomment-6110524656) 轉錄，每列三類之和等於合計）：

| 2026-10-05 | 外資及陸資（不含外資自營商） | 投信 | 自營商（自行買賣＋避險） | 合計 |
| --- | ---: | ---: | ---: | ---: |
| 3105 | 28,396,840 | 2,812,800 | 2,350,894 | 33,560,534 |
| 3293 | 6,386,218 | 414,000 | -12,792 | 6,787,426 |
| 5274 | -28,586 | -40,427 | 10,254 | -58,759 |
| 5347 | 323,290 | 3,600,607 | 339,261 | 4,263,158 |
| 6488 | 354,337 | 1,179,529 | -62,262 | 1,471,604 |
| 6510 | 186,887 | -594,227 | 32,887 | -374,453 |
| 8069 | -4,247,384 | -13,040 | 64,380 | -4,196,044 |

| 2026-10-06 | 外資及陸資（不含外資自營商） | 投信 | 自營商（自行買賣＋避險） | 合計 |
| --- | ---: | ---: | ---: | ---: |
| 3105 | 27,460,450 | 2,352,400 | 2,227,304 | 32,040,154 |
| 3293 | 5,507,085 | 420,000 | -11,177 | 5,915,908 |
| 5274 | -13,315 | -66,756 | 8,894 | -71,177 |
| 5347 | 8,820,683 | 3,720,607 | 407,416 | 12,948,706 |
| 6488 | 594,644 | 1,330,929 | -11,515 | 1,914,058 |
| 6510 | 87,416 | -660,897 | 43,724 | -529,757 |
| 8069 | -4,053,731 | -9,040 | 285,782 | -3,776,989 |

### 47.7 完整署名

609 UTF-8 bytes，與外部 policy 的 `rights.attribution` 及 QA 收據末段逐字相同：

> 金融監督管理委員會證券期貨局提供、財團法人中華民國證券櫃檯買賣中心（Taipei Exchange, TPEx）[2026] 上櫃股票三大法人買賣明細資訊（dataset11856；dataset-11856-dated-csv/issue36-two-cutoffs-v1）。此開放資料依政府資料開放授權條款（Open Government Data License）進行公眾釋出，使用者於遵守本條款各項規定之前提下，得利用之。政府資料開放授權條款－第1版：https://data.gov.tw/license。原欄、來源及完整性保留；2026-10-05與2026-10-06各五日三法人淨股數及合計為本地衍生結果。

### 47.8 未驗與限制

- qa2 額度已用盡：六個 URL 皆 SPENT、seal 已花用、原件已自 RAM 撤銷。任何再取需新的明示授權與新 seal，NO-RETRY 照舊；不 restart、replay、clone 或 hydrate 已釋放的原件。
- 窗口和為零未出現，該情形只有合成證據；401、403、429 路徑未被真實觸發；真實來源上的首敗即停只由 qa1 的失敗驗到；真實資料的負向（壞欄、缺列）只有合成證據。
- 閘門是進程內協作式防護，不是沙箱，僅 Windows；retained estimate 不是 RSS 或 peak，生命週期驗收不代表實體抹除。
- Policy 的 `admission_authority.source_use_receipt` 仍指向 [留言 6088463678](https://github.com/YiCheng0608/stock-lab/issues/36#issuecomment-6088463678)（qa1 的授權），模組不交叉比對；qa2 由使用者收據、模組常數與 seal 三處綁定。
- 官方查詢 SLA 未知；只對這六個日期、七股、這個來源與本地 RAM 用途有效。Policy 明列不支援：PIT、publication、first availability、revision lineage、adjustment、20 日成交值分母、`shares ÷ TWD` 的無因次策略門檻、完整歷史成員、hot group、strategy、Signal、Plan、API、UI、DB、cross-process，以及其他日期、路由與 provider；`denominator`、`amount`、`strategy`、`historical_pit` 在 consumer 皆為 `unsupported`。
- 母單 #21 的整體 AC（分母、金額語意、PIT、策略等）不因本節而解除。

## 48. #31 qa1／qa2／qa3：七股 FinMind 融資餘額與兩截止五日變動比（ordinary-margin-cutoffs-1005-1006-v2）

2026-10-12。#31 以 FinMind `TaiwanStockMarginPurchaseShortSale` 取得七股 2026-09-24～2026-10-09 的融資原件，供 2026-10-05、2026-10-06 兩個截止日各含截止日向前五個間隔（六個交易日）的 `MarginPurchaseTodayBalance` 變動比 consumer（產品 `backend/app/tpex_margin_balance_source.py`，測試 `backend/tests/test_tpex_margin_balance_source.py`）。本節只管理這個新 namespace，不提升也不改寫其他節的 policy、pins、capture 或 default；日曆用 [§31.2](#312-24日完整觀測日曆與20日金融集合)的已驗交易日，不由日曆推導。取得過程與 QA 收據保存在 [#31](https://github.com/YiCheng0608/stock-lab/issues/31)，下列為摘要並附留言編號。

### 48.1 版本、外部 pins 與上限

| 項目 | 內容 |
| --- | --- |
| 外部 policy | schema `ordinary-margin-source-policy/v2`；canonical 2,886 UTF-8 bytes（sorted keys、compact JSON、無尾 LF）；SHA-256 `7d8cd5b1835b84138e2bc982d86a93d4b3b4a3bba809842341c279fe566a9ceb`。由全局發布於 [#31 留言 6112134098](https://github.com/YiCheng0608/stock-lab/issues/31#issuecomment-6112134098)，產品不能由被測 policy 自建 expected |
| source／consumer | provider FinMind，dataset `TaiwanStockMarginPurchaseShortSale`；consumer `ordinary-margin-change-ratio-v1`，version `ordinary-margin-cutoffs-1005-1006-v2`：14 個 consumer（兩截止 × 七股），每個含 6 個 `MarginPurchaseTodayBalance` |
| namespace | `issue31-margin-seven-cutoffs-1005-1006-v1/qa3`（字串中的 `v1` 是 namespace 名稱，不是 policy 版本） |
| 標的與日期 | TPEx 3105／3293／5274／5347／6488／6510／8069；請求範圍 2026-09-24～2026-10-09；已驗交易日 2026-09-24、09-29、09-30、10-01、10-02、10-05、10-06（09-25、09-28 為閉日） |
| 窗口 | 2026-10-05：09-24、09-29、09-30、10-01、10-02、10-05；2026-10-06：09-29、09-30、10-01、10-02、10-05、10-06 |
| 請求 | 固定 7 個 GET，依上列標的次序：`https://api.finmindtrade.com/api/v4/data`，query 依序 `dataset=TaiwanStockMarginPurchaseShortSale`、`data_id=<代號>`、`start_date=2026-09-24`、`end_date=2026-10-09`；標頭只有 `Accept-Encoding: identity` 與 `User-Agent: stock-lab-issue31-local-ram/1`（stdlib 另加 `Host`）；不換 provider、日期或路由 |
| 上限 | 每份 body 1 MiB、aggregate raw 8 MiB、retained-roots estimate 32 MiB（estimate 不是 RSS 或 peak）；每 URL 20 s、整批 180 s（cooperative）；redirect 0、retry 0、cookie／token／proxy 0；每 URL 最多 1 次；首敗即停且 attempted 即 SPENT；只在 RAM |

### 48.2 用途、授權與署名

用途只限免費公開、個人非商用、本地盤後研究與 RAM 取得／驗證／consumer。Policy `supportedUse`：`local_personal_noncommercial`、`process_ram_snapshot`、`margin5_balance_change_ratio`；`unsupportedUse`：`historical_pit`、`publication_time`、`first_availability`、`revision_history`、`historical_eligibility`、`historical_membership`、`actionable_strategy`、`plan`、`trading`、`disk_raw_storage`、`raw_redistribution`、`mirror`、`deployment`、`other_cutoff`、`official_unit_verification`。產品的 `UseRequest` 只接受預設值，其餘用途一律 `unsupported_use`。FinMind 是服務提供者，不是官方直接來源；完整署名見 [§48.6](#486-完整署名)。

qa1、qa2、qa3 各是獨立的一次額度。qa2、qa3 是使用者的新授權，不是恢復前一個，qa1、qa2 的 SPENT／NO-RETRY 照舊。授權本身不是 seal，每次 real run 另須全局核發 fresh financial-start seal，並由獨立 QA 執行一次。

| 項目 | qa1 | qa2 | qa3 |
| --- | --- | --- | --- |
| 來源方案 | AC 修訂 1：TPEx 官方 current CSV 1 件＋FinMind 7 件（最多 8 GET） | 同 qa1 | AC 修訂 2：FinMind 7 件（最多 7 GET），不取官方 CSV |
| namespace | `issue31-margin-seven-cutoffs-1005-1006-v1/qa1` | `issue31-margin-seven-cutoffs-1005-1006-v1/qa2` | `issue31-margin-seven-cutoffs-1005-1006-v1/qa3` |
| 授權／准入 | [留言 6084167671](https://github.com/YiCheng0608/stock-lab/issues/31#issuecomment-6084167671)（全局取得方案准入與 policy v1 pin） | 使用者 [留言 6110713412](https://github.com/YiCheng0608/stock-lab/issues/31#issuecomment-6110713412)，全局 [留言 6110894588](https://github.com/YiCheng0608/stock-lab/issues/31#issuecomment-6110894588)（namespace） | 使用者 [留言 6111567857](https://github.com/YiCheng0608/stock-lab/issues/31#issuecomment-6111567857)（qa3 額度）與 [留言 6111752011](https://github.com/YiCheng0608/stock-lab/issues/31#issuecomment-6111752011)（改 FinMind-only，取代 URL 清單），全局 [留言 6111788122](https://github.com/YiCheng0608/stock-lab/issues/31#issuecomment-6111788122)（AC 修訂 2 核定） |
| seal | [留言 6087448056](https://github.com/YiCheng0608/stock-lab/issues/31#issuecomment-6087448056) | 授權收據 [留言 6111507978](https://github.com/YiCheng0608/stock-lab/issues/31#issuecomment-6111507978)，raw [留言 6111513090](https://github.com/YiCheng0608/stock-lab/issues/31#issuecomment-6111513090) | 授權收據 [留言 6113129628](https://github.com/YiCheng0608/stock-lab/issues/31#issuecomment-6113129628)，raw [留言 6113132856](https://github.com/YiCheng0608/stock-lab/issues/31#issuecomment-6113132856)，1,207 B |
| seal pin（seal raw 的 SHA-256） | 見 [留言 6087463996](https://github.com/YiCheng0608/stock-lab/issues/31#issuecomment-6087463996) | `914fb9bdcb65eb840602a11b1f2fbaea234f8bd79f79222754b4dd74d82c03b9`（[留言 6111514728](https://github.com/YiCheng0608/stock-lab/issues/31#issuecomment-6111514728)） | `27856f011aad791100019bc6d9d188ecb9f3c6ca8efa49de66ef5719196eb432`（[留言 6113135218](https://github.com/YiCheng0608/stock-lab/issues/31#issuecomment-6113135218)） |
| seal 有效期（UTC） | 2026-10-09 19:05:33～19:35:33 | 2026-10-11 17:06:51～17:51:51 | 2026-10-11 20:00:29～20:45:29 |
| candidate | `68e54a50fbf0c077e61b5b652d6bcfa8d564e998` | `9f4e55fb1abb47f87eb0f1b2f6f9ea474ecf6b99` | `0ea75e0b45ab0720e303293a1faeb0d159bbdf58` |
| 產品檔 SHA-256 | `1e6c4537d35f3a78370492365eaf818286db26f87b2176e1a9e743b2a81b62e1` | `6476f538ec32384ac44a664d69eb4fe74a2c55abdb5e301cdd33a2ba60ca8517` | `e6f656997c90d7fc921278813f350064f607a3a64c559944c19ffa66e644969e` |

qa3 之後產品檔只有模組 docstring 末句不同（改為記載 qa3 已觀測一次），程式內容不變，因此 qa3 的真實來源證據沿用；不是 qa3 當時執行的位元組，雜湊以提交後的 blob 為準。

### 48.3 原件驗證與五日變動比計算

- **取得**：只接受 HTTP 200（其他狀態含 redirect 一律拒用，出現 `location` 即 `http_redirect`）、identity encoding（無 `content-encoding`，或其值為 `identity`），媒體型別 `application/json`（可帶 `charset=utf-8` 或 `charset="utf-8"` 參數，其他參數與媒體型別拒用）；完整 EOF 與 raw hash 通過後才 parse。`content-length`、`transfer-encoding`、`content-encoding`、`content-type`、`location` 任一重複即 fail-closed，其他標頭重複（如 `cache-control`、`vary`、`set-cookie`）不影響結果；不送出、不使用、不保存 cookie。以 stdlib 直接建立連線；`http.client.HTTPSConnection` 被替換時以 `transport_class_replaced` 在花用額度前拒用，稽核須以 `connection_factory` 組合包裝。
- **JSON 與 envelope**：strict UTF-8、無 BOM（BOM 以 `bom_rejected` 拒用）；envelope 恰為 `msg`、`status`、`data` 三鍵，`status` 為 200、`msg` 為 `"success"`，`data` 為 1～10,000 列。
- **列結構**：FinMind 文件的 16 欄中，必要 15 欄（`date`、`stock_id` 為字串，其餘 13 欄為 0 至 int64 上限的非 bool 整數）；`Note` 可選（缺欄、`null` 或至多 256 字元的字串），不進任何計算；任何其他鍵拒用。`date` 只收 ISO `YYYY-MM-DD`、落在 2026-09-24～2026-10-09 且唯一；`stock_id` 等於請求代號。
- **內部一致性**（取代官方 anchor）：每股依日期排序後，到 2026-10-06 的日期恰為七個已驗交易日；2026-10-06 之後至少有一列；相鄰列 `MarginPurchaseYesterdayBalance[i+1] == MarginPurchaseTodayBalance[i]`（含 10-06 之後的連結）；七股的日期集合相同。2026-10-06 之後的列只作鏈式核對，不進任何窗口。任一不符整批拒用，不補值、不縮窗。
- **單位**：「張」（lots）、scale 1 是明示的 provider 推論（`providerLiteral=false`、`officialAnchorVerified=false`），沒有官方 anchor 驗證。
- **計算**：每股每窗口取 6 個 `MarginPurchaseTodayBalance`，變動比 `(B[T]-B[T-5])/abs(B[T-5])`，以整數分子與正分母（`abs(B[T-5])`）表示；門檻 `<= 0.05` 以精確整數比較 `20*分子 <= 正分母`，四捨五入的顯示值不進閘門；分母為 0 則整批拒用。公式與門檻與正式 canonical（`backend/worker/pipeline.py` `_margin_change_ratio`、`backend/app/domain.py` `maximum_balance_change_ratio`）一致；差異只在產品用精確整數／`Fraction`，canonical 用浮點。

### 48.4 SPENT 帳

- **qa1**（2026-10-09，[收據 6087747180](https://github.com/YiCheng0608/stock-lab/issues/31#issuecomment-6087747180)）：第 1 個請求（TPEx 官方 current CSV）attempted 即 SPENT，在 connection constructor 失敗，傳輸 0 byte、無 status；七件 FinMind 未嘗試。原因為全局靜態推論（原 exception 類別與訊息未保存）：QA harness 把 `http.client.HTTPSConnection` 換成包裝類別，使 stdlib 原類別 `__init__` 內的 `super(HTTPSConnection, self)` 解析到被替換的名稱；上述 `transport_class_replaced` 閘門處理這個狀態。
- **qa2**（2026-10-11 17:09 UTC，[收據 6111546400](https://github.com/YiCheng0608/stock-lab/issues/31#issuecomment-6111546400)）：官方 CSV `https://www.tpex.org.tw/web/stock/margin_trading/margin_balance/margin_bal_result.php?l=zh-tw&o=data` 回 HTTP 200，`Content-Type: application/csv;charset=utf-8`，產品在讀 body 前以 `http_content_type` 拒用；attempted 即 SPENT，body 0 byte；七件 FinMind 未嘗試。
- **qa3**（2026-10-11 20:03 UTC，[收據 6113180452](https://github.com/YiCheng0608/stock-lab/issues/31#issuecomment-6113180452)）：七件 FinMind 依序各 1 次，全部成功，原 exit 0；沒有未嘗試的 URL。
- qa1、qa2 的官方 CSV URL 維持 SPENT／NO-RETRY；AC 修訂 2 起產品不含該 URL 或任何 TPEx 官方件，policy v1（qa1、qa2 namespace）的文字與 pin 不再被接受。qa3 額度已用盡，任何再取需新的明示授權、新 namespace 與新 seal；不 restart、replay、clone 或 hydrate 已釋放的原件。

### 48.5 qa3 觀測到的回應形狀

[留言 6113180452](https://github.com/YiCheng0608/stock-lab/issues/31#issuecomment-6113180452) 的一次觀測（逐件 body SHA-256、起迄時間見該收據），不是 FinMind 對形狀的承諾：

- 七件皆 `HTTP/1.1 200`、`Server: uvicorn`，媒體型別 `application/json`，有 `Content-Length` 且等於 body 實際長度，無 `Content-Encoding`、無 `Transfer-Encoding`、無 `Location`；回應標頭名稱恰為 `access-control-allow-origin`、`content-length`、`content-type`、`date`、`server`（5 個）。匿名（無 token、無 cookie）呼叫未被要求登入或付費。
- body 3,545～3,732 B，七件合計 25,489 B。
- 每股 9 列，七股日期集合相同：2026-09-24、09-29、09-30、10-01、10-02、10-05、10-06、10-07、10-08（10-06 之後兩列，沒有 10-09 列）。七股 × 9 列只有一種鍵集合，共 16 鍵（15 必要鍵＋`Note`），`Note` 63 列都是字串；相鄰日期對 `Yesterday[i+1] == Today[i]` 56 條全部成立。

### 48.6 完整署名

273 UTF-8 bytes，與產品常數 `ATTRIBUTION` 逐字相同：

> FinMind: TaiwanStockMarginPurchaseShortSale; local personal noncommercial RAM snapshot only; no raw redistribution/mirror. FinMind is the service provider; this is not an official direct feed and the lot unit is an explicit provider inference, not an official verification.

### 48.7 未驗與限制

- **餘額與比值只在 RAM 驗證，沒有保存**：qa3 證明真實來源可被產品取得、嚴格解析並通過獨立 oracle；它不產生可供其他功能取用的資料，再取數值需新額度與新 seal。
- **單位「張」是推論**：沒有官方 anchor；AC 修訂 2 移除官方同日對照後，數值與單位只有 FinMind 內部一致性（鏈式、日期集合）支持。
- **`Note` 缺欄與 `null` 只有合成證據**：真實樣本 63 列都是字串；數值上限 256 字元是 policy 邊界，不是 FinMind 文件事實。
- **最後一列是 2026-10-08**：沒有 10-09 列，原因未核；閘門只要求 10-06 之後至少一列且不晚於 10-09。
- **非 PIT，不證穩定**：發布時間、首次可得、修訂歷史與歷史 eligibility 未知；匿名 7 次成功不證匿名額度、限流或 FinMind 的長期穩定。
- 到期後拒用與 qa3 candidate 的失敗路徑清除只有合成證據（qa3 一次成功，未觸發）；閘門是進程內協作式防護，不是沙箱；retained estimate 不是 RSS 或 peak，生命週期驗收不代表實體抹除。
- 只對這七股、這兩個截止日、這個 dataset 與本地 RAM 用途有效；TWSE、其他市場、其他 cutoff、PIT、策略、Plan、API、UI、DB、cross-process 均不支援。母單 #21 的整體 AC 不因本節而解除。
