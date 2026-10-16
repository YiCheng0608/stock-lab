# Source registry、用途 gate 與官方來源契約

本文負責官方來源 identity、授權、用途 gate、capture 與 consumer 契約。各節有限 review 不代表其餘來源已重新查證、全市場 coverage 或 PIT。

本文件是免費公開官方來源的 identity、授權、用途 decision、runtime capture 與已接 consumer 的權威。第 3 節是原 snapshot 四來源，第 8 節是另需 explicit 單來源 manifest 的 TPEx 單日法人，第 13 節是獨立版本的政府連結 CSV policy；不能將新增來源當成 bundled default 或沿用舊 registry version。一次 HTTP 200、來源名稱或資料日期都不能補成完整 coverage、發布時間、first availability、revision lineage 或 historical PIT。

## 來源選用原則（FinMind 為主）

新的取得方案、恢復的暫停單與新來源准入，先以 FinMind（`https://api.finmindtrade.com/api/v4/data`）為主要來源；FinMind 沒有該資料集或無法滿足用途時，才另提其他來源，並在原 Issue 記理由。只用 FinMind 時，官方 anchor 改為 FinMind 內部一致性核對，單位與 scale 寫成明示推論並列入該來源節的限制；需要其他來源（含官方核對）時另提方案。

用途限免費、本地個人非商用研究；署名、不 mirror、不再散布 raw 等權利界線見下節 [FinMind 來源共同規則](#finmind-來源共同規則)。FinMind 要求付費、登入，或回 401／402／403 即停止，不在同一額度內重試；改用其他來源須依上段另提方案。本原則是來源方向，不是取源授權：每次真實取得仍須具體範圍（URL、次數、caps），依 [§1](#1-registry-與-policy-契約) 的版本化 policy 與 pin，並有單一 namespace 與核發前經使用者確認的 seal（見下節）；已 SPENT／NO-RETRY 的額度不因本原則恢復。

### FinMind 來源共同規則

本節是 §47 以後各節（§47～§53 及 #9、#39、#98 節） 這類「外部 policy＋namespace＋seal」RAM 取得 namespace 的共同規則（§47 的來源是 TPEx dated CSV，署名依 OGL，其餘流程相同）；各節只保留版本字串、pins、本節特有上限與差異。

- **用途**：只限免費公開、本地個人非商用、盤後研究與 process RAM 取得／驗證／consumer；不落盤（[§52](#52-7七股普通收盤與交易日曆的日期時區語意契約) 例外：依使用者決策 D2(b)，衍生收盤落盤到私人 root，raw 不落盤）、不發布 raw、不鏡像、不再散布、不部署、不交易。`historical_pit` 不支援，publication／first availability／revision 固定 `unknown`；其他 cutoff、代號、dataset 與用途在取數前拒用，不外推。FinMind 是服務提供者，不是官方直接來源；只用 FinMind 時沒有官方 anchor，單位與 scale 是明示的 provider 推論，比對只是同一份 bytes 的內部一致性。免費使用是文件推論（`token` 選填），FinMind 回 401、402、403 或任何要求付費、登入的回應即首敗。
- **額度與 seal**：每個 namespace（`…/qaN`）是獨立的一次額度；新授權不是恢復前一個，前一個的 SPENT／NO-RETRY 照舊並登錄於[治理 #1](https://github.com/YiCheng0608/stock-lab/issues/1)。使用者授權本身不是 seal：每次 real run 另須全局核發 fresh financial-start seal（綁定 policy SHA-256、namespace、唯一 URL 清單、candidate、產品／測試／script hash、用途、caps 與有效期），由獨立 QA 執行一次；產品不能由被測 policy 自建 expected pin，policy、seal 或 execution binding 不符在 GET 之前拒絕、不花額度。每 URL 最多 1 次、首敗即停且 attempted 即 SPENT；redirect 0、retry 0、token／cookie／proxy 0、identity encoding；原件只在 RAM，結束後 release 並撤銷 handle。再取需新的明示授權、新 namespace 與新 seal；不 restart、replay、clone 或 hydrate 已釋放的原件。
- **防護性質**：閘門、audit hook 與 trace 是進程內協作式防護，不是沙箱，僅 Windows；每 URL／整批 timeout 為 cooperative 檢查，不是 OS 硬 deadline；retained-roots estimate 是 deduplicated `getsizeof` 估算，不是 RSS 或 peak；生命週期驗收不代表實體抹除。
- **署名**：署名方式依各版本 policy 宣告。§47（TPEx，[§47.7](#477-完整署名)）與 §48（FinMind，[§48.6](#486-完整署名)）的 policy 有固定完整署名文字，產品常數須逐字相同；§52 與 #98 節的 policy 有固定 `attribution` 字串（固定在被 pin 的 policy 內，隨 policy SHA-256 被 seal 綁定，並寫入保存的 receipt），§53 的 policy 有 FinMind、TWSE、TPEx 三段固定署名文字；§49、§51、#9 節與 #39 節的 policy 沒有固定完整署名文字，也不引用 FinMind 條款全文或版本，以 `rights` 字串 `FinMind personal noncommercial local RAM; attribution; no raw redistribution or mirror` 與 provenance 的結構化來源欄（如 `FinMind TaiwanStockPrice data_id=TAIEX (personal noncommercial; attribution; no mirror/raw redistribution)`）承擔署名，並隨 policy SHA-256 被 seal 綁定。權利是否充分是使用者決策，QA 只核對它被 seal 綁定。

## 現行節次索引

各版本 policy、pins 與 capture 彼此獨立；新 explicit 版本不提升舊 default、不沿用舊 capture bytes，也不作 implicit latest。已歸檔節次與子節不在本文，查 Git 指標；`git show f431b9885cd3332ddd328309d0041a15c55b8610:docs/SOURCE_REGISTRY.md` 取得歸檔前全文，下表連結為該版本的行範圍。

| 節 | 範圍 | 現況與歸檔指標 |
| --- | --- | --- |
| [原則](#來源選用原則finmind-為主) | 全專案來源選用原則（FinMind 為主） | 現行 |
| [§1](#1-registry-與-policy-契約) | Registry 與 policy 契約（顯式 manifest、registry_version 與 canonical digest 的 pin 判定） | 現行 |
| [§2](#2-官方共同證據與限制) | 官方共同證據與限制 | 現行 |
| [§3](#3-四個准入來源) | 原 snapshot 四個准入來源 | 現行 |
| [§4](#4-standalone-source-capture) | Standalone source capture 執行入口 | 現行 |
| [§5](#5-兩個-capture-consumers) | 兩個 capture consumers：`STOCK_DAY_ALL` selected bars（5.1）、`holidaySchedule` 正面排除（5.2） | 現行 |
| [§6](#6-tpextwse-有限資料品質契約) | TPEx／TWSE 有限資料品質契約 | 現行 |
| [§7](#7-review-receipt-與未完成範圍) | 原 snapshot Registry pin 與未完成範圍 | 現行；7.1～7.3 review 證據已移出，查節內 Git 指標 |
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
| [§49](#49-32-qa1qa2七股-finmind-nominal-ohlcv-日線-last60-與兩截止-raw-算術issue32-seven-nominal-ohlcv-two-cutoffs-v1) | #32 qa1／qa2：七股 FinMind nominal OHLCV 日線 last60 與兩截止 raw 算術（`issue32-seven-nominal-ohlcv-two-cutoffs-v1`） | 現行 |
| [§50](#50-97七股-tpex-靜態規則表tpex-static-rules2026-10-12v1) | #97：七股 TPEx 靜態規則表（`tpex-static-rules/2026-10-12/v1`）；tick、交易時段、賣方證交稅與手續費門檻的讀用契約 | 現行 |
| [§51](#51-33taiex-名目指數兩截止-21-觀測-returnissue33-taiex-nominal-observation-cutoffs-1005-1006-v1) | #33：TAIEX 名目指數兩截止 21 觀測 return（`issue33-taiex-nominal-observation-cutoffs-1005-1006-v1`，FinMind-only） | 現行 |
| [#9](#9-qa1七股-finmind-自行買賣與避險五日淨額原件issue9-dealer-direction-combos-finmind-v2) | #9 qa1：七股 FinMind 自行買賣與避險五日淨額原件（`issue9-dealer-direction-combos-finmind-v2`） | 現行 |
| [#39](#39-qa1七股-finmind-法人買賣與成交量及兩截止流向量比率issue39-seven-flow-to-volume-ratio-two-cutoffs-v1) | #39 qa1：七股 FinMind 法人買賣與成交量及兩截止流向÷量比率（`issue39-seven-flow-to-volume-ratio-two-cutoffs-v1`） | 現行 |
| [§52](#52-7七股普通收盤與交易日曆的日期時區語意契約) | #7：七股普通收盤取得、私人衍生值保存與讀回（`issue7-ordinary-close-saved-seven-v1`）；日期／時區語意契約 | 現行 |
| [#98](#98七股-finmind-交易日曆停復牌間接證據與公司行動因子issue98-tpex-seven-calendar-actions-v2) | #98：七股 FinMind 交易日曆、停復牌間接證據與公司行動因子（`issue98-tpex-seven-calendar-actions-v2`）；日狀態、除權息／減資／分割因子、私人保存與讀用 | 現行 |
| [§53](#53-37七股所涉群組兩截止推論-membership-與-ram-lookupissue37-industry-membership-inferred-cutoffs-1005-1006-v1) | #37：七股所涉群組兩截止推論 membership 與 RAM lookup（`issue37-industry-membership-inferred-cutoffs-1005-1006-v1`） | 現行 |

#9、#39、#98 三節以 Issue 編號命名，不另編節號。

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

有限 review 的範圍：四個 allowlisted endpoint 的 capture shape、condition receipts、exclusive publish 與失敗不發布（live 只涵蓋 `STOCK_DAY_ALL` 與一次 `holidaySchedule`）、`STOCK_DAY_ALL` 完整 body validation 與 selected Decimal OHLCV、`holidaySchedule` exact fields／窄 closed grammar／多日 positive exclusion；不構成全市場、session、完整 calendar 或 PIT 證據。

仍未完成：

- 原四來源已有 `STOCK_DAY_ALL` 與 `holidaySchedule` 兩個有限磁碟 ZIP capture consumers；第 9 節另為 TWT48U selected 事件新增已有限 review 的記憶體 consumer，不支持既有 ZIP 讀入。TWT48U selected／feed 的有限產品接線由[個股頁 §11–13](STOCK_RESEARCH_PAGE.md#11-m1-p3bselected-官方事件總覽接線)負責；Event／News 持久化、`tpex_spendi_history` capture 接線與完整 legacy collector gate 仍缺。
- `historical_pit` 需逐筆 first-available、revision/withdrawal lineage及可重建 snapshots；event/date/current raw不能替代。
- `tpex_spendi_today` 不在四來源 manifest；完整 halt/action/session/TAIEX truth、C007 store linkage、B5b/PIT與正式資料分類仍未完成。
- Paid subscription、TWSE/TPEx action identity/duplicate修正、generic numeric hardening、舊資料 repair與既有 evaluation replay仍需獨立設計及授權。

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/SOURCE_REGISTRY.md` §7.1、§7.2、§7.3。

## 8. M1-P2a：TPEx 日法人來源與 selected 摘要

M1-P2a 是解除 M1 的 TPEx 日法人 source gate 的必要基礎批次，來源准入、capture／selected 摘要及下述具名驗收已有限 review。只採 exact `GET https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading`，另以 explicit [`tpex_institutional_registry.json`](../backend/worker/tpex_institutional_registry.json) 單來源 manifest 執行；原第 3 節 snapshot、bundled default 與其 pins 不變。此准入不放行 legacy `dailyTrade` 或 TWSE `T86`；後續單日總覽接線另依[個股頁 §10](STOCK_RESEARCH_PAGE.md#10-m1-p2b單日法人原件總覽接線)，不由 P2a 來源准入直接宣稱產品完成。

單來源 pins 為 `registry_version=m1-p2a-tpex-institutional-2026-10-03.1`、`content_digest=sha256:7ca17724e029c6a417dd2baa1981e6396d74772e977aecd1e823fde0e0090146`；`source_id=tpex_3insti_daily_trading`、`source_version=tpex-3insti-daily-trading-oas3-info1.0.0-2026-10-03`。Source version 是本地查證 snapshot 名稱，不能當成官方保留的 revision 或歷史版本鏈。

### 8.1 官方證據與用途邊界

統籌於 **2026-10-03** 核對：

- [政府資料集 11856](https://data.gov.tw/dataset/11856) 記載免費、每日更新與政府資料開放授權條款第 1 版，並連到 TPEx OpenAPI。
- [TPEx Swagger](https://www.tpex.org.tw/openapi/swagger.json) 是 OAS 3.0、info version `1.0.0`、server `https://www.tpex.org.tw/openapi/v1`；exact GET path `/tpex_3insti_daily_trading` 的名稱為「上櫃股票三大法人買賣明細資訊」，未列 parameters／security，info 明示歡迎介接。這是 exact OpenAPI 介接證據，不外推任意網站自動下載。
- OGL 1.0 與 TPEx 網站條款的核對同 [§13.1](#131-獨立-policy-與四用途)。

`free_public_local` 的 `local_fetch`、`raw_store`、`summarize` 取得有限准入，仍須分別履行 bounded request／endpoint limit、顯名、原件完整性、版本／hash／時間與 traceability 條件。`historical_pit` 為 `unsupported`；精確發布時鐘、逐筆 first availability、完整歷史、revision／withdrawal lineage、數字配額與 endpoint-specific deprecation 皆未知。每日更新與來源 `Date` 不代表可重建交易日曆或歷史當時可得版本。

TWSE `T86` 保持用途准入證據 `unknown`：本次 [TWSE Swagger](https://openapi.twse.com.tw/v1/swagger.json) 未找到該 path，亦未取得對應 exact dataset／介接同意；[TWSE 使用條款](https://www.twse.com.tw/zh/terms/use.html) 第 6 點的自動下載限制不能由 legacy endpoint 可讀而略過。此結論不稱 TWSE 明文禁止 `T86`，也不由 TPEx 的正面證據放行 TWSE。

### 8.2 Selected 摘要契約與操作

[`tpex_institutional_capture.py`](../backend/worker/tpex_institutional_capture.py) 提供 `summarize_capture(...)` 與 `summarize_capture_bytes(...)`，輸出版本為 `tpex-institutional-selected/v1`。Consumer 只讀既有 `capture.zip`，在記憶體驗證，不解壓、改寫原件、寫 DB 或送網路 request；每次需 explicit manifest／profile、兩個外部 pins、Gregorian expected date 與非空、無重複 selected symbols。

以**股**（`unit=shares`）為單位，分開輸出**外資及陸資（不含外資自營商）**、**投信**與**自營商**的 buy／sell／net。只接受 canonical ASCII 整數字串：buy／sell 非負，net 可帶正負，範圍為正負 `9223372036854775807`；空白、逗號、單位、小數、科學記號、前導零與 `-0` 均拒收。各類須滿足 `net = buy - sell`，`TotalDifference` 必須等於三類 net 合計；外資自營商不得再加一次。合法來源零保留零，缺值、無效或不一致不補零；任一 requested selected 不合格即整份摘要 unavailable，CLI exit 2 並給具體 reason，成功 exit 0。

全 body 為非空 JSON object array；每列 `Date` 僅接受七碼民國 `ROC_YYYMMDD` 且須等於 caller 的 expected date，security code 非空，requested selected 各須恰有一列。只驗 selected 的公司名、三組數量與合計，不將其他列的數量稱為已核對；duplicate JSON key 或非有限數值仍拒收。外資 total-sell 的 exact source key 含**前導空白**，不自行改欄名；每個 buy／sell／net 的 `source_fields` 隨摘要保存。

Consumer 重驗 ZIP_STORED exact `body.bin`／`receipt.json` 成員、大小及 body hash、successful receipt、source／endpoint／GET／版本／pins、型別敏感的 policy／condition／attribution 內容及 aware、順序一致的 request／capture time；檔案讀取前後重驗 identity／bytes，拒絕 symlink、hardlink 或途中變更。摘要保存 body／receipt 雙 hash、原件 1-based row ordinal、capture time、來源與版本、attribution、summarize decision 及 condition receipts。`provenance.verification=local_evidence_consistent` 只證本地原件／receipt 一致，不是官方 origin authentication。

`candidate_count` 是全 body 列數，`selected_count` 是本次合格選列數，`as_of` 是顯式 expected data date；`session_windows.status=unavailable`，保留 `trading_session_source_not_admitted` 與 `multi_session_institutional_evidence_missing`。Selected `status=available` 不代表 5／20 交易日窗口 available。拒收以 reason code 回報，主要有 `payload_date_mismatch`（列 `Date` 不等於 expected date）、`selected_row_missing`／`selected_row_duplicate`（requested selected 無列或多列），以及外部 pins 與 receipt／manifest digest 不符；清單不封閉，以程式為準。

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

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/SOURCE_REGISTRY.md` §8.3。

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

此 memory consumer 不支持既有 ZIP 讀入；P3a 本身不接 API／UI／DB，`durable_capture=false`、`historical_pit=unsupported`。Live body／receipt 不保存，不能離線重播；再取得的內容／版本可能不同，Git fixture 只重建邊界測試。後續 M1-P3b 的 selected 總覽接線見[個股頁 §11](STOCK_RESEARCH_PAGE.md#11-m1-p3bselected-官方事件總覽接線)，不由產品接線擴張本節來源與時間邊界。

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/SOURCE_REGISTRY.md` §9.3。

## 10. M1 後續依賴審查：來源候選與等待邊界

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/SOURCE_REGISTRY.md` §10。

## 11. M2-P1：本次官方事件 feed 摘要

**程式及下述具名驗收已 review（有限）。** 本批只支援既有 `twse_twt48u_all`、exact GET、`free_public_local` profile 與第 9 節原 manifest／source version／雙 pins，不新增准入或修改原 snapshot。Memory capture、receipt 與各用途條件仍依第 9.2 節；[`twse_action_capture.py`](../backend/worker/twse_action_capture.py) 新增 `summarize_memory_feed(...)`，輸出 `twse-action-observed-feed/v1`、`validation_scope=all_observed_identity_dates_classification`，供官方事件關注清單使用。

與 selected 摘要分開，全 feed 摘要接受 JSON object array，包括合法空 `[]`；逐列驗 exact `Code`、nonblank `Name`、有效七碼 ASCII 民國 `Date`、exact `Exdividend=息/權/權息`，相同 `Code + Date + Exdividend` 重複拒收，不以 alias 或猜測補 canonical 欄位。任一列不合格即整份 unavailable，不挑剩餘列湊清單。Duplicate JSON keys、非有限值及不合格 receipt／pins／hash／時間仍拒收。這是全 body 身分、日期與分類的驗證，不放行未驗金融欄位、全市場 completeness 或事件歷史。

摘要保留原件列序、原值身分／日期／分類、effective-date 角色、body／receipt 雙 hash、request／capture UTC、固定版本與 attribution／purpose／condition receipts。空摘要只證本次合格原件零列，不是官方全市場「沒有事件」；不以空結果推導單股缺 selected 可用。第 9 節 selected API 的非空請求與缺 selected 拒收契約維持。

`candidate_count` 是全 body 列數，`selected_count` 是合格事件列數；全 feed 版本將全部來源代碼排序放入 `selected_symbols`，每股事件保持原件列序，與 requested-symbol selected 版本分開。合法空 `[]` 回 available、兩個 count 都是 0、`selected_symbols=[]`，仍有 receipt、雙 hash 與顯名／用途條件；之後 selected 讀同一空原件仍以 `nonempty_row_list_required` 拒收。非空 feed 的任何 invalid code／日期／名稱／分類、重複事件、非 object row 或非 list payload，分別保留 `invalid_security_code`、`invalid_effective_date`、`selected_name_missing`、`selected_event_class_unknown`、`selected_event_duplicate`、`row_object_required`、`row_list_required`；`selected_*` 在本函式指全部觀測列，不表示只檢查某幾股。

來源日期仍是生效日，capture time 只是本次觀測；published／first available／revision 仍 unknown，`historical_pit=unsupported`。Consumer 不寫 DB／檔案／ZIP，不形成調整因子、價格影響或利多分類。本次 feed 到關注清單、最多 100 股與已知 catalogue 的 M1 連結由[個股頁 §12](STOCK_RESEARCH_PAGE.md#12-m2-p1官方事件關注清單接個股總覽)負責，產品接線不擴大來源准入或時間支持範圍。

M2-P2 在完整 feed consumer 驗證後才按來源 `Code`／任一 `Name` 搜尋，符合結果再排序及套 100 股上限，匹配外或上限外的壞列不得跳過；搜尋不改原件事件列數、摘要版本或原件 bytes／pins。本批不新增來源／用途准入或歷史支持，來源正負向與產品驗收分開；精確搜尋／計數／返回契約及本次支持範圍由[個股頁 §13](STOCK_RESEARCH_PAGE.md#13-m2-p2官方事件清單搜尋與研究往返)負責。空 feed、同股多事件、上限及拒收只有記憶體 fixture 證據，不作全市場證據；原件未保存，不能離線重播。

## 12. M1-P4a：TWSE 單日法人有界審查與准入缺口

統籌已接受 **2026-10-03** 的有界可行性及程式唯讀審查，支援 M1 的 TWSE 單日法人來源評估；**來源未准入，等待精確證據**。本輪只核對官方頁面／metadata、用途權利及既有接線，不取得法人原件，不新增 consumer、API／UI、manifest 或 pins，不增加能力完成度。這是依賴等待，不是使用者暫停，也不表示 ROADMAP 全部餘項受阻。

### 12.1 官方證據與用途邊界

| 官方來源 | 當次核對與限制 |
| --- | --- |
| [TWSE T86 公開查詢頁](https://www.twse.com.tw/zh/trading/foreign/t86.html) | 頁面提供日期、分類及 CSV 入口，提示資訊自民國 `101-05-02` 起提供。這只證 UI 提示，未取得當次法人 body，不證完整歷史、實際欄位、單位或 selected 數值。 |
| [TWSE OpenAPI UI](https://openapi.twse.com.tw/)／[Swagger metadata](https://openapi.twse.com.tw/v1/swagger.json) | 程式以唯一一次 raw Swagger GET 檢查 **143 個 paths**，當次未見 `T86`。搜尋 `fund`／`insti`／`foreign`／`T86` 及三大法人／三法人／投信／自營商，僅找到 `MI_QFIIS_cat`、`MI_QFIIS_sort_20`；兩者為持股股數／比率，不能代替三類法人買賣流量。官方 UI 顯示 version `1.0`／OAS 2.0，不能據此補成 raw 回應的版本證據。 |
| [TWSE 使用條款](https://www.twse.com.tw/zh/terms/use.html) | 第 6 點要求自動下載依同意的方式，第 8 點另列政府開放資料例外；查詢頁可看或舊 collector 可取，均不能代替 exact 資源／方式的准入證據。 |
| [政府資料開放授權條款第 1 版](https://data.gov.tw/license) | OGL 1.0 適用已釋出的資料。本輪官方搜尋未取得 TWSE exact 個股三類買賣流量資源與授權的對應；不能由 TPEx 資料集 11856、其他已准入 OpenAPI 或網站可讀外推。 |

Exact TWSE 候選的 `local_fetch`、`raw_store`、`summarize` 權利證據仍為 `unknown`，用途未准入；本輪未建立或變更 manifest decision。欠缺正面證據不改寫成 `explicitly_prohibited`，也不宣稱 TWSE 全面禁止或永久不可用。

恢復條件依序為：取得 exact 官方 TWSE 資源／方式對免費 `local_fetch`、`raw_store`、`summarize` 的正面權利證據（政府開放資料的 exact 對應或其他官方明示授權，不跨資源移轉）；統籌核定一次有界、純記憶體的完整單日 body，核實實際欄位、資料日、單位、完整回應與具名 selected（成功讀取本身不算 gate 通過）；gate 滿足後才另准 explicit 最小來源准入、consumer 白名單與單日總覽子能力。完整 5／20 交易日基準及 PIT 不作本批單日前置。

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/SOURCE_REGISTRY.md` §12.2、§12.3。

## 13. M1-W1：TPEx 多日法人與完整有界交易日

本節是 W 系列的共同基礎：§13.1 政府連結 CSV 來源與用途、§13.2 完整有界日曆規則、§13.3 原件／整數／缺日契約；[§19](#19-m1-w8八截止法人來源與完整有界日曆) 與 [§31](#31-m1-chips-cutoff-1006-1同1006法人窗口與完整有界日曆) 沿用。W1 當時的 policy 與取得上限不是現行設定，現行 policy 見 [§19.1](#191-新版policy用途與取得上限)。

W1 範圍：TPEx 3105／6488、唯一資料截止2026-10-02，日曆限2026-09-01～10-02；不計完整 M1 或 PIT。W2 同截止 API／UI 見[個股頁 §18](STOCK_RESEARCH_PAGE.md#18-m1-w2同截止法人窗口與原件追溯)。

### 13.1 獨立 policy 與四用途

[`tpex_institutional_window.py`](../backend/worker/tpex_institutional_window.py) 的現行 policy、profile、外部 pins 與取得上限見 [§19.1](#191-新版policy用途與取得上限)；型別／來源集合、四用途、整份 policy 與外部 digest 必須一致。W1 當時的 policy `tpex-institutional-window/w1-v1`、外部 pin `m1-w1-tpex-window-2026-10-04.1` 已由 §19.1 版本取代，digest 與原文見 `git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/SOURCE_REGISTRY.md` §13.1。原 registry／policy JSON、P2a manifest、bundled default 與其 pins 未改。

| Source ID／版本 | 准入的政府連結 exact GET 與觀測查詢 |
| --- | --- |
| `tpex_government_institutional_csv`；`dataset-11856-dated-csv-observed-2026-10-04/v1` | [dataset11856](https://data.gov.tw/dataset/11856) 的 [CSV](https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data)，附 `d=115/MM/DD`，僅下述20個日期。 |
| `tpex_government_index_csv`；`dataset-11391-month-csv-observed-2026-10-04/v1` | [dataset11391](https://data.gov.tw/dataset/11391) 的 [指數 CSV](https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?response=data)，附 `date=2026/09/01` 或 `2026/10/01`。 |

統籌核實這兩個政府連結資源免費、適用[政府資料開放授權條款第1版](https://data.gov.tw/license)，及[TPEx 網站條款](https://www.tpex.org.tw/zh-tw/gtsm_disclaimer.html?l=zh-tw)第7點的開放資料例外；條款第 5 點限定經同意方式自動下載的限制保留，不因 endpoint 可讀而消失，各節「條款核對同 §13.1」均含此限制。`local_fetch`、`raw_store`、`summarize` 各為 `admitted`，須署名 Taipei Exchange (TPEx)、保留授權／政府資料集／exact URL、原件完整性、hash、版本及取得時間，並履行有界請求。`historical_pit=unsupported`；這不放行 legacy POST、其他日期、TWSE 或任意自動下載。查詢日期參數是本次實測行為，不是官方參數 SLA；數字 rate limit、精確發布／first availability、revision lineage 及停用承諾仍未知。

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

dataset11370 的 OGL 1.0 與 TPEx 條款核對同 [§13.1](#131-獨立-policy-與四用途)。此exact政府資源的 `local_fetch`、`raw_store`、`summarize` 有限admitted，仍須有界取得、顯名、完整性、原件hash／版本／時間及traceability；本輪只process memory，raw_store准入沒有授權磁碟保存。署名保留「證期局＋櫃買中心／上櫃股票行情／2026／OGL1.0」，data-date為2026-10-05。不放行legacy POST、附加 `d` 的歷史查詢、其他URL或任意自動下載，`historical_pit=unsupported`。

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

Windows private path保護目前只驗Windows；未提供其他平台保證。核定product root為`%LOCALAPPDATA%/taiwan-stock-research/price-save-01a11367`，final子目錄`tpex-11370-2026-10-06-m1-v1`；max one bundle／3files、raw≤3MiB、capture receipt≤8KiB、storage receipt≤16KiB、合計≤3170304B。測試quota、精確殘留及清理拒絕由[開發入口](development-baseline/README.md#m1-price-save-1-私人磁碟保存與新程序驗證入口)詳述；本准入不是其他scope的磁碟grant。

既有私人三檔（1791644B／3files）已達 file count cap：不新增磁碟案例，也不 copy／export／publish；其清理依[治理 #1](https://github.com/YiCheng0608/stock-lab/issues/1)登錄的授權與 NO-RETRY 條件處理，不以本節授權。

## 31. M1-CHIPS-CUTOFF-1006-1：同10/06法人窗口與完整有界日曆

本節定義 explicit 10/06 同截止法人窗口的來源用途、完整24日曆與金融真值。僅TPEx3105穩懋／6488環球晶、explicit `as_of=2026-10-06`；原件為當次事後觀測、process memory，非PIT。§19 W8的3613B canonical／SHA `6a7e4aa786edf6ff801d411daeb254623ca9dce4815b771d51aa9a57e1da89cb`、截止10/02及worker／API pins immutable；舊六價格canonicals與default日期不自動提升。產品操作見[個股頁 §36](STOCK_RESEARCH_PAGE.md#36-m1-chips-cutoff-1006-1同截止法人窗口與完整日曆)。

### 31.1 Exact集合、用途與版本

新policy `m1-chips-cutoff-tpex-2026-10-06.1`，profile `free_public_local`；canonical UTF-8 **4264B**，外部 `policy_digest=sha256:36c761a5f6e22afee86ad414769b88c06e97ae792141879a5660cf0856c180d5`。完整policy／exact集合／用途／scope及digest須同時匹配，不能自行計算expected pin或沿用W8、global registry、單日price／private storage grant。

| Source ID／observed版本 | 准入GET資源與exact參數 |
| --- | --- |
| `tpex_government_index_csv`／`dataset-11391-month-csv-observed-2026-10-07/chips-v1` | [dataset11391](https://data.gov.tw/dataset/11391) exact [inx](https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?response=data)，`date=2026/09/01`及`2026/10/01`（wire依URL encoding）；先驗全部返回月列。 |
| `tpex_government_institutional_csv`／`dataset-11856-dated-csv-observed-2026-10-07/chips-v1` | [dataset11856](https://data.gov.tw/dataset/11856) exact [dated daily](https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data)，`d=115/MM/DD`只限下述20 required sessions。 |

兩 dataset 的 OGL 1.0 與 TPEx 條款核對同 [§13.1](#131-獨立-policy-與四用途)，另核[平日交易規則](https://www.tpex.org.tw/zh-tw/mainboard/trading/rules/system.html)與[11503027221休市公告](https://www.tpex.org.tw/storage/eb_data/11509/11503027221.html)。新grant只准此集合的 `local_fetch/raw_store/summarize`，raw_store本輪只process memory，不授權磁碟／正式DB或任意自動下載。署名保留櫃買中心、兩dataset、OGL1.0及資料／觀測版本；publication、first availability、revision time／lineage與數字rate limit未知，`historical_pit=unsupported`。

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

唯一existing bundle為 `%LOCALAPPDATA%/taiwan-stock-research/price-save-01a11367/tpex-11370-2026-10-06-m1-v1/`。Literal三檔、原canonical schema／bytes／SHA及Windows path保護仍由[§30.2](#302-三檔原子出版與嚴格重驗)與[§33.2](#332-existing-private有限只讀)管理。原capture `storage=process_memory`／`request_count=1`是歷史capture事實；當前來源另標 `origin=private_local`、storage receipt仍 `private_local`。Augmented provenance不當作原canonical receipt重算hash。

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

唯一root `%LOCALAPPDATA%/taiwan-stock-research/price-save-01a11367`、bundle `tpex-11370-2026-10-06-m1-v1`；原1791644B／3files／3dirs全raw／canonical／mtimeNS重驗：

| literal file／bytes | SHA-256 | mtime_ns |
| --- | --- | --- |
| body.csv／1788599 | `ab34590df051d7ba08f35941811b69ee35f46c890212558b9f089119307b3200` | 1791329565505432100 |
| capture-receipt.json／1461 | `871a6887a3b87bd7c23c20fc3a25ec98d369d0df2ed8eedbe8cb040e5242cd36` | 1791329565507431000 |
| storage-receipt.json／1584 | `436465b4d13d604965327fe1be7eff98edf65274b0f16c7871474280feb0197b` | 1791329565509430100 |

Raw/capture/storage caps3145728/8192/16384B，bundle≤3170304B／one bundle。Shared64bundle/192file reads含ROOT，producer ceiling61＋ROOT3。Entry/apply/switch/back無明示read則private0。

Price UTC2026-10-06 started23:32:17.666931／captured23:32:21.005311／saved23:32:45.499432；publication/first availability/revision unknown、PIT unsupported。Snapshot10s cooperative／graph32MiB，非OS硬deadline/RSS/peak。

### 33.3 Fresh金融集合/guards

只准SINGLE NEW empty producer／capture_attempt1，external metadataGET0、price financialGET0；trusted首次chips POST才取得§31 exact2 index＋20daily＝22 official GET。API與preview各自在upstream前限 `POST /api/stocks/TPEx/(3105|6488)/institutional-windows/capture?as_of=2026-10-06`；query一次，非空UTF8 body≤4096B且須空JSON物件，壞body/query422、oversize413、其他POST405。其他五股不capture；GET unknown/duplicate query先422，舊/prices/saved405，focus unsupported日期先unavailable/private0。UI核saved detail context／五RAW。

僅admitted chips network context准exact HTTP／TPEx443 DNS-connect；上限同 [§31.3](#313-一次取得與可證執行上限)，另 joint retained graph≤96MiB（estimate）。

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

TPEx basic 原件（Date1151006／893列）核 6223旺矽：掛牌20030106、industry24、preferred0／NTD10，准入operational ordinary TPEx／TWD。CFI與ISIN未核實，不能稱ISIN catalogue已驗或PIT membership。

[政府dataset11370](https://data.gov.tw/api/v2/rest/dataset/11370)連至[exact TPEx daily CSV](https://www.tpex.org.tw/web/stock/aftertrading/DAILY_CLOSE_quotes/stk_quote_result.php?l=zh-tw&o=data)；OGL 1.0 與 TPEx 條款核對同 [§13.1](#131-獨立-policy-與四用途)。只准入bounded process-memory用途；不授權保存、歷史參數或其他資源，引用／產品追溯仍須保留來源署名及原件完整性。

新policy `m2-stock-scope-tpex-11370-2026-10-07.1`：canonical UTF-8 **1564B**，digest `sha256:bdad10af9090dd15319b3f3e8dca2952f75c4caf6d46b3032e706a5006ccbab2`；deep copy舊.5，只改version／cutoff／八股集合／bodySHA／release_version。新worker `tpex-price-capture/m2-stock-scope-v6`、projection `stock-price-memory/m2-stock-scope-v6`、consumer `price-lot-focus/m2-v10`，sourceversion `tpex-11370/2026-10-07`。10/07只explicit採用，不提升old defaults；不hydrate舊body或擴private／chips scope。

上限：ROOT OBS1＋ONE empty producer FIRST 各一次 GET；body cap3MiB；headers16KiB為收到後檢查；30s cooperative；graph32MiB estimate；redirect0／retry0／disk0。兩GET後禁retry／restart／newproducer。

10/07 body：1793305B、SHA256 `eaa1eaf37ff3e2305629dced8b0f6945a063b05841c69d75f826960e6bd819c8`，12245 data rows／width18／Date1151007／date-code unique。6223 真值：O/H/L/C＝5590／5725／5480／5530元／股、canonical896441股＝896.441張、TWD成交額4984488555元，O/C為down；振幅沿既有exact公式，門檻4.382含6223、4.383排除6223，不按顯示約值filter。完整八股required reads及身份／金融／cutoff／pins／provenance先gate後filter，任一缺失或衝突仍unavailable／count=null／items=[]，只有完整八股available才可判真零。Source-date10/07與capture UTC分開；publication／first availability／revision unknown、historical_pit unsupported。

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/SOURCE_REGISTRY.md` §35.2、§35.3。

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

條款核對同 [§13.1](#131-獨立-policy-與四用途)，exact用途沿§31；本批另准ONE新empty producer、memory-only有限22 GET（上限同 [§31.3](#313-一次取得與可證執行上限)），不取得metadata或普通股price。兩month index為2026/09/01及10/01，daily為9/07～10/06的既有exact20日期；原daily URL／query沿§31，redirect／retry0。新parser先驗ALL25原月列150欄及date uniqueness，再採≤10/06 exact24 observed dates；完整保留合法10/07原六欄供追溯但不採入窗口。9/25／9/28closure notice保持；last20為9/07～10/06、last5為9/30／10/01／10/02／10/05／10/06，不補零／縮窗／推休市／用index代ordinary stock closes。

### 36.2 Actual原件與獨立淨超

兩股 12 nets 的數值同 [§31.4](#314-12-net-金融真值)（本批以新來源獨立重算，結果相同）；外資不含外資自營商，canonical shares、精確張及口徑保持。Publication／first availability／revision unknown，historical PIT unsupported。上限同 [§31.3](#313-一次取得與可證執行上限)；private32MiB／joint96MiB與10s snapshot為estimate／cooperative。

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/SOURCE_REGISTRY.md` §36.3、§36.4。

## 37. M1-SAVED-PRICE-CHIPS-FOCUS-STOCK-SCOPE-7-1006-1：七股共同來源准入

ROOT有限接受同explicit2026-10-06的saved七股＋七股法人共同範圍；新增3293鈊象／5274／5347／6510／8069，3105／6488也由本次新來源重驗。舊兩股§36及其政策、原件、失敗與未跑項保持；操作由[個股頁 §42](STOCK_RESEARCH_PAGE.md#42-m1-saved-price-chips-focus-stock-scope-7-1006-1七股八條件與同截止往返)管理，不回寫舊calendar negative card為已驗。

### 37.1 獨立准入、版本與來源集合

ROOT先核定用途／有限來源／private READ與下列canonical UTF-8 policies及外部pins，才implementation／GET／private IO；不能從received policy自建expected digest。

| Policy version | Bytes／SHA-256 |
| --- | --- |
| m1-chips-cutoff-stock-scope-7-tpex-2026-10-06.1 | 6742／`b2f939100bd76de12bd974abb80f267596bf5a55f839271a5f4cc61409f9c220` |
| m1-saved-price-chips-integration-stock-scope-7-tpex-2026-10-06.1 | 13404／`8e55142cce367fd44d64ea9d6d9e756c1fdd5b091c928669bbe94de1df950de8` |
| m1-saved-price-chips-focus-stock-scope-7-tpex-2026-10-06.1 | 17021／`2f6d3a91337363e5700d7fdf6c16c63b8a14f45362d4407c8b73b01dabfe860e` |

New profile `free_public_local_full_month_cutoff_stock_scope_7`；worker `tpex-institutional-window/chips-1006-stock-scope-7-v1`，summary `tpex-institutional-window-summary/chips-1006-stock-scope-7-v1`，capture `tpex-institutional-memory-capture/chips-1006-stock-scope-7-v1`，calendar `tpex-observed-calendar/chips-1006-stock-scope-7-v1`。API `institutional-windows/chips-1006-stock-scope-7-v1`與read `institutional-windows-read/chips-1006-stock-scope-7-v1`分開；entry `saved-price-chips-entry-stock-scope-7/m1-v1`、focus `price-saved-chips-focus-stock-scope-7/m1-v1`。

Calendar version `tpex-2026-09-01_2026-10-06-full-month-observed-2026-10-07-11503027221/chips-stock-scope-7-v1`；daily/index source versions分別為 `dataset-11856-dated-csv-observed-2026-10-07/chips-stock-scope-7-v1`／`dataset-11391-month-csv-observed-2026-10-07/chips-stock-scope-7-v1`。Old pure/calendar全bytes、原三price policies／pins與defaults不改；七股普通TPEx／TWD身份與同10/06保存價格沿§29／32，法人identity/name另由本次140列逐列重驗。

條款核對同 [§13.1](#131-獨立-policy-與四用途)，exact用途沿§31；另准ONE新empty producer、trusted FIRST一次、memory-only 2index＋20daily（上限同 [§31.3](#313-一次取得與可證執行上限)）。Month index2026/09/01、10/01；ALL25原月列150欄與日期唯一性先驗，再採≤10/06 exact24，合法10/07原六欄保留但不進窗口。Last20為9/07～10/06，last5為9/30／10/01／10/02／10/05／10/06；9/25／9/28 closure notices保持。Exact daily URL/query沿§31；不補零／縮窗／推休市，index不能代ordinary stock closes。

每次先完整ALL7 price＋ALL7 chips／calendar／20daily／5及20窗口／同cutoff／pins／provenance，再filter；高price門檻或先得零仍不得省略七股法人。Only full available才count0，missing／invalid／conflict為count=null／items=[]，不縮scope／跳壞股／補零。Initial saved unread只mask price；actual current source failure同時mask BOTH，恢復須same-generation明示NEW private＋held chips雙成功。Private三檔沿§33.2只READ-only，禁止新增保存／copy／export／publish／delete。

### 37.2 Actual原件與42個精確窗口值

七股 42 個窗口值如下（3105／6488 的數值同 [§31.4](#314-12-net-金融真值)，不重列）；canonical單位為股，精確張除1000。

| 股／窗口 | 外資shares | 投信shares | 自營商shares |
| --- | --- | --- | --- |
| 3293／5 | 5507085 | 420000 | -11177 |
| 3293／20 | 9668934 | 1500000 | 78845 |
| 5274／5 | -13315 | -66756 | 8894 |
| 5274／20 | 177907 | -18788 | -5046 |
| 5347／5 | 8820683 | 3720607 | 407416 |
| 5347／20 | 44867613 | 8655386 | 2676428 |
| 6510／5 | 87416 | -660897 | 43724 |
| 6510／20 | -319920 | -406908 | 99835 |
| 8069／5 | -4053731 | -9040 | 285782 |
| 8069／20 | -9278025 | -252940 | 294173 |

外資不含外資自營商；5／20／三類所有aggregate須在signed int64內，scope7專屬overflow guard拒越界，不影響old calendar版本。原精確價格／O-C方向／振幅式及signed張grammar／inclusive AND見§32.2／34.1，不改公式或用顯示約值filter。Publication／firstavailability／revision unknown，historical PIT unsupported。上限同 [§31.3](#313-一次取得與可證執行上限)；private32MiB／joint96MiB及10s snapshot為estimate／cooperative。

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/SOURCE_REGISTRY.md` §37.3、§37.4。

## 38. M1-CHIPS-STOCK-SCOPE-7-DAILY-NET-TREND-20-1006-1：七股每日法人淨超與窗口累計

ROOT已有限接受本批chips-only核心操作；同explicit2026-10-06、普通TPEx／TWD七股3105／3293／5274／5347／6488／6510／8069，外資不含外資自營商、投信、自營商各別5／20日每日淨超及窗口累計。操作及actual邊界由[個股頁 §43](STOCK_RESEARCH_PAGE.md#43-m1-chips-stock-scope-7-daily-net-trend-20-1006-1七股每日淨超與累計操作)管理。本節新版本獨立；§37及old calendar政策、defaults、失敗、pending與未跑歷史原樣保持，不能以本次接受回寫舊驗收。

### 38.1 獨立政策與有界來源

ROOT原task的precise admission先於implementation／financial GET；獨立canonical policy `m1-chips-daily-net-series-stock-scope-7-tpex-2026-10-06.1`，9733 UTF-8 bytes，外部SHA-256 `143aabb4cd2d86110d5564793ce77b0fb6c60b3e603f23c1e188875934a48a31`。Expected pin不得由received policy自建。New profile `free_public_local_chips_only_daily_net_series_stock_scope_7`；worker `tpex-institutional-series/chips-stock-scope-7-v1`、capture `tpex-institutional-series-capture/chips-stock-scope-7-v1`、read `institutional-daily-net-series-read/chips-stock-scope-7-v1`，計算版本 `signed-daily-net-running-sum/window-reset-int64-v1`。Old producers／profiles immutable；只有純解析與數值函式可重用，不restart／clone／hydrate／replay／preload或用old capture取代新來源。

條款核對同 [§13.1](#131-獨立-policy-與四用途)，exact用途沿[§31](#31-m1-chips-cutoff-1006-1同1006法人窗口與完整有界日曆)，只另准ONE empty producer的FIRST一次：2份2026/09/01、10/01月index＋9/07～10/06 last20 daily，exact URL/query、HTTP200／CSV UTF-8／identity依canonical policy；上限同 [§31.3](#313-一次取得與可證執行上限)，GET診斷回應界線16MiB。Daily source version `dataset-11856-dated-csv-observed-2026-10-07/chips-daily-net-series-stock-scope-7-v1`；index為 `dataset-11391-month-csv-observed-2026-10-07/chips-daily-net-series-stock-scope-7-v1`。

先驗ALL25月原列／150原字串與日期唯一性，再採≤10/06 exact24；10/07六原欄保留追溯而不採入。Last20為9/07～10/06，last5為9/30、10/01、10/02、10/05、10/06；9/25／9/28 closure沿原契約。Index是observed calendar，不能當普通股收盤序列；缺列不推休市、不補零／縮窗／跳壞股。新觀測或來源不符合exact bound即停止，不重試或機械續抓。

### 38.2 每日、累計與完整性契約

Canonical為signed int64股，以canonical integer string傳遞；張精確除1000、最多三位小數，既有單位公式不改。各窗口從第一日前的0重新累計，按日期做exact prefix sum；5日不延用20日累計起點。每個dated point／row保留ALL25原字串、原列ordinal、body SHA-256、original canonical receipt SHA-256與calendar。

ALL7×兩窗口×三法人須完整驗daily、aggregate及每個running prefix，才可顯示任何available series或合法零。任一daily／aggregate／prefix超過−9223372036854775808～9223372036854775807，整個七股profile unavailable，不只拒目前所選股。ALL42期末累計必須等於獨立窗口淨超和；source relations與component檢查沿完整25欄口徑。Unknown／missing／conflict不能變0，亦不能以先得到零省略ALL7 gate。

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/SOURCE_REGISTRY.md` §38.3、§38.4。

## 39. 2026-10-08：歷史收盤新候選審查與官方事件重選

本次新FinMind primary核對提供 [TaiwanStockPrice technical API線索](https://finmind.github.io/tutor/TaiwanMarket/Technical/)，與舊Sponsor broker候選分開。[2026-07-13使用條款](https://finmindtrade.com/analysis/#/Sponsor/terms_of_use)與[2026-07-12 disclaimer／licenses](https://finmindtrade.com/analysis/#/Sponsor/disclaimer)依方案界定API／SDK服務用途；服務不包含對外再散布／轉售／鏡像，對外公開仍須自行確認原資料機關授權要求。這些證據當時尚未建立exact普通股歷史source owner／rights／各用途與獨立calendar／consumer pins；MIT軟體license或一般公開管道聲明不代data permission。普通股日線已於 [§49](#49-32-qa1qa2七股-finmind-nominal-ohlcv-日線-last60-與兩截止-raw-算術issue32-seven-nominal-ohlcv-two-cutoffs-v1) 以 FinMind `TaiwanStockPrice` 取得；本節只保留當時的候選審查結論，不構成全域禁止。

`M2-OFFICIAL-EVENT-DATE-RANGE-20261008-1` 只沿[§9](#9-m1-p3atwt48u-selected-官方事件原件摘要)／[§11](#11-m2-p1本次官方事件-feed-摘要)已准入exact TWT48U／free_public_local／原registry、digest、sourceversion與pins。[政府dataset89748](https://data.gov.tw/dataset/89748)免費／OGL1.0／不定期、metadata詮釋更新2026-06-30；[TWSE Swagger](https://openapi.twse.com.tw/v1/swagger.json) info1.0、exact GET／十二string欄、Date為除權息日期；metadata更新日不是事件availability。fresh financial GET 上限：body≤5MiB、20秒per-operation／30秒cooperative／redirect0／retry0、body／receipt只RAM。新consumer `official-event-focus/p3-v1` 的range只投影effective date，完整feed／receipt驗後才篩選；精確計數、API及具名操作由[個股頁 §44](STOCK_RESEARCH_PAGE.md#44-m2-official-event-date-range-20261008-1官方事件日期區間與研究往返)管理。published／first available／revision仍unknown，historical PIT unsupported；capture time不代發布，synthetic catalogue不證普通股／行情。

### 39.1 M2-OFFICIAL-EVENT-DATE-RANGE-20261008-1：實際來源結果

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/SOURCE_REGISTRY.md` §39.1。

## 40. M2-OFFICIAL-EVENT-KIND-20261008-1/B1：事件類型實際來源與有限接受

Consumer `official-event-focus/p4-v1`：精確息／權／權息配effective range／q，完整feed先驗後篩；API及可信desktop／窄版操作見[個股頁](STOCK_RESEARCH_PAGE.md) §45。來源沿§9／§39：exact GET `/exchangeReport/TWT48U_ALL`、registry `r1-a1-c009-2026-09-12.1`、external digest `sha256:eb6c290d7716300c4117bb2cdc61a66cbf8d62e344870928933b44b77461f87b`、source_version `twse-twt48u-all-d011-2026-09-12`／free_public_local 與原雙 pins 不改；OGL 1.0 與 TWSE 使用條款第6同意方式／第8政府資料例外依 [§2](#2-官方共同證據與限制)。local_fetch／raw_store 僅 RAM，summarize 保留 TWSE 署名、完整性及 trace。

上限：body 5MiB／identity／per-operation 20秒（實際httpx 15秒）／30秒cooperative，非hard deadline；retry／redirect／warmup 0，首次失敗亦 SPENT、focus／selected 共享 seal。本能力只按 Date 生效日，不需交易日 calendar；published／first availability／revision unknown，historical PIT unsupported。synthetic 4（0056 ETF／1449／1463／2614）只 routing，不證 ordinary／行情／全市場；payout numeric／forecast／Plan／save 未驗。

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/SOURCE_REGISTRY.md` §40。

## 41. M1-TWSE-ISSUER-EVENT-PROFILE-20261008-1/B1：真 issuer 與同截止事件有限接受

2026-10-08。1449／1463／2614真TWSE公司六原欄trace、同cutoff官方事件與原五條件返回已有限接受；local_fetch／raw_store只RAM／summarize須TWSE署名、完整性／追溯，不含磁碟／private／account／historical PIT授權。行為與具名操作見[個股頁 §46](STOCK_RESEARCH_PAGE.md)。

[Gov dataset18419](https://data.gov.tw/api/v2/rest/dataset/18419)：license1／costfree、modified2024-11-25，distribution CSV `https://mopsfin.twse.com.tw/opendata/t187ap03_L.csv`，notes明示Swagger；modified不代公司出表／availability。[TWSE Swagger](https://openapi.twse.com.tw/v1/swagger.json) exact HTTPS GET `/opendata/t187ap03_L` 宣告33 string fields，exact TWT48U12欄保持；金融top-array／全33原string及schema由actual FIRST核，不只憑Swagger當transport通過。

OGL 1.0／TWSE使用條款第6 approved method／第8政府資料例外依 [§2](#2-官方共同證據與限制)。上限：各producer ONE exact HTTPS GET／NEW empty獨立generation／single attempt，FIRST失敗亦SPENT；5MiB／identity／per-operation上限20秒（實際timeout15）／30秒cooperative、redirect／retry／warmup0；完整原body與ORIGINAL receipt只同RAM物件。capital／payout numeric **NOT VALIDATED**。新獨立[issuer code manifest](../backend/worker/twse_issuer_registry.json)：sourceversion `twse-t187ap03-l-d18419-2026-10-08`、registry `twse-issuer-r1-2026-10-08.1`／external digest `sha256:7488da20a3bdf94aaa548c896d19077628bf93529208226d49b2a02896972f89`、source profile `twse_issuer_free_public_local`；consumer `twse-issuer-event-profile/m1-v1`／external policy digest `sha256:02bf2422129c46490516557bccd188f7d550d2516c4b5e49e9acc2faf5338244` 已ROOT review。DOC不另建manifest附件；原四source／defaults／pins及§40完整不變。

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/SOURCE_REGISTRY.md` §41.1、§41.3。

### 41.2 同代號原欄位與時間

| Code | 原全名／簡稱 | 原上市日／ISO | 原industry | issuer／event ordinal |
| --- | --- | --- | --- | --- |
| 1449 | 佳和實業股份有限公司／佳和 | 19920506／1992-05-06 | 04 | 78／46 |
| 1463 | 強盛新投資控股股份有限公司／強盛新 | 19961205／1996-12-05 | 04 | 88／47 |
| 2614 | 東森國際股份有限公司／東森 | 19950923／1995-09-23 | 20 | 440／51 |

Taipei觀測10/08、研究cutoff2026-10-08；公司原出表1151007／ISO2026-10-07，不當發布／first availability。公司Code exact join eventCode；issuer全名／簡稱與eventName分列，三股eventName各exact等於原簡稱；事件Name若不等任一公司原名即unavailable，duplicate／conflict拒用、不silent overwrite／fallback。出表ROC7、上市Gregorian8或ROC7 strict有效，raw與ISO保留；report／listing／Taipei observed／cutoff／effective event日分離，published／first availability／revision仍unknown、nonPIT。行業只原04／20，不證產業名稱／分類品質／ordinary／0056ETF／fullmarket／price／capital數值；0056issuer不支持，不由此判斷security類型。

## 42. M1-TWSE-ISSUER-INDUSTRY-TRACE-20261008-1/B1：兩碼引用與同截止原件

2026-10-08。兩完整TWSE碼名有來源引用本地研究、兩fresh金融原件與可信desktop／narrow操作已有限接受，不外推完整M1／M2／M3。分類語意見[產業 §10](INDUSTRY_CLASSIFICATION.md)，操作及待驗見[個股頁 §47](STOCK_RESEARCH_PAGE.md)，驗證入口見[開發入口](development-baseline/README.md)。

### 42.1 官方引用與用途

| 官方證據 | 本輪核對內容／日期角色 |
| --- | --- |
| [TWSE B.12.00](https://www.twse.com.tw/staticFiles/product/broker/ff80808166388ea1016676ac941001e0.pdf) | 附錄三完整 `04＝紡織纖維`、`20＝其他`；printed p92／zero-based p100／parsed104頁。107/10修訂、109/03實施，分別2018-10／2020-03，保留month precision。 |
| [2023產業格式公告](https://eshop.twse.com.tw/zh/news/detail/0000000087e9b84901886b8d96940024) | published2023-05-30、patch effective2023-07-03；16更名及35–38新增作版本脈絡，不代公司分類生效。 |
| [FL007104第2條](https://twse-regulation.twse.com.tw/TW/law/DAT0201_print.aspx?FLCODE=FL007104) | 修正2025-06-09；33名稱清單仍含兩完整名稱，並非本輪完整code表或2026完整current證明。 |

以上是ROOT核對的 `parsed_official_document`，沒有原始文件body／ORIGINAL receipt SHA，不能捏造PDF／公告／規則raw傳輸雜湊。依[TWSE使用條款](https://www.twse.com.tw/zh/terms/use.html) §8，ROOT本輪限縮解釋僅准兩條完整碼名的本地研究引用，條件為identify_source及preserve_complete_name_integrity；不將政府issuer資料OGL移轉為整碼表OGL，不准完整表重發布或原文件下載／保存。此引用不證完整current taxonomy、ordinary／ETF身分、membership、公司分類effective／PIT或策略。

新[引用registry](../backend/worker/twse_industry_registry.json)：`twse-industry-citation-r1-2026-10-08.1`／profile `twse_two_code_complete_name_local_citation`，external registry digest `sha256:75b7667f65a9da7397a72a1e9c494a35364f7563faedc4df2cda21f12e61b647`；consumer `twse-issuer-industry-trace/m1-v1`／policy digest `sha256:e9815a28d0ec22d29cd82c5524b02612debff4fec0110465002f6016afbae9b8`。引用宣告version `twse-two-code-citations/b12-notice-fl007104-2025-06-09-v1`／canonical ROOT-attested excerpt digest `sha256:dfba7e99fdb9343d71b34361afc04c0198a3ab1ebc31ff8a175fee588aa0fac8`；這些是canonical宣告pin，不是來源文件raw SHA。原四源defaults／pins、issuer v1及§41原契約保持。

Issuer／event 原件沿§41的 exact GET、RAM-only 與上限；industry 是同資料的 pure-read 投影，不新增 producer／外網／DB 寫入。selected 1449／1463／2614 的原 industry 碼 04／04／20 分別引用紡織纖維／紡織纖維／其他；公司六原欄、原Code／Name exact join 與 report1151007／listing 日期沿§41.2，capital／issuedshares／payout numeric NOT VALIDATED。publication／firstavailability／revision 與公司分類生效仍 unknown／nonPIT。

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/SOURCE_REGISTRY.md` §42.2、§42.3。

## 43. M1-CHIPS-STOCK-SCOPE-7-GROSS-TRADE-20-1006-1/B1：七股gross買賣與新來源准入

2026-10-08。ROOT precise grant先於implementation／financialGET；fresh原件／數值／具名操作已有限接受。本節只管理本B1獨立政策與來源／數值契約；已接受§31／37／38、oldprofiles／defaultpins、failed producer及其未跑歷史不改。新操作及完成條件見[個股頁 §48](STOCK_RESEARCH_PAGE.md)；[ROADMAP_EXECUTION](ROADMAP_EXECUTION.md) 只供歷史對照，現行任務狀態只在 GitHub Issues／Projects。

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

取得：ONE NEW empty producer、trusted FIRST一次，程序不得probeGET／seed；先2 index exact [inx](https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?response=data)（`date=2026/09/01`、`2026/10/01`），驗日曆後採last20，才取exact [dated daily](https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data)的calendar-derived `d=115/MM/DD`（9/07～10/06）；最多2＋20＝22GET，1 attempt失敗亦SPENT，redirect／retry／warmup0；FIRST_once及cached 409，切股／套用／back／held READ不得另fetch。上限同 [§31.3](#313-一次取得與可證執行上限)，診斷16MiB。ALL22 ORIGINAL body及未增補canonical receipts只RAM，不得用augmented provenance重造receipt或以相同bodySHA冒fresh original；0 privateIO／priceGET／DB／product artifacts，保存／跨程序未授。

### 43.2 新metadata核對、用途與署名

[REST11391](https://data.gov.tw/api/v2/rest/dataset/11391)「Index historical data」與[REST11856](https://data.gov.tw/api/v2/rest/dataset/11856)「Information on the trading details of OTC stocks three major institutional investors」，owner櫃買中心／TPEx、license1／free／CSV UTF-8／exact resource URL已核，metadata不代金融原件。

OGL 1.0 與 TPEx 條款核對同 [§13.1](#131-獨立-policy-與四用途)，另核[交易規則](https://www.tpex.org.tw/zh-tw/mainboard/trading/rules/system.html)及[11503027221公告](https://www.tpex.org.tw/storage/eb_data/11509/11503027221.html)；僅准本B1 `local_fetch/raw_store/summarize`，raw_store限processRAM，summarize限gross買／賣／net本地研究。完整署名保留owner／year2026／上述兩完整dataset名／observedversions／OGL1.0 URL，保留原件完整性。Metadata發布／修改時間不代金融row發布；published／firstavailability／revisionunknown，nonPIT／historical PIT unsupported，不授權磁碟保存／正式DB／採購／帳戶／交易或任意自動抓取。

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/SOURCE_REGISTRY.md` §43.3、§43.5。

### 43.4 全日曆、ALL25原欄與gross計算

不硬沿舊25rows。兩月**全部返回**原6欄先驗日期／unique／requested month／weekday／nonclosed／≤observation10-08／finite positiveOHLC及上下界；postcutoff合法原列完整保留追溯而不採，不假定25或26列，不從缺列推休市。採≤10/06的完整24weekday正面集合扣公告9/25、9/28，與§31 required24相符；last20為9/07～10/06，last5為9/30、10/1、10/2、10/5、10/6。完整calendar不代ordinary stock20／21closes或MA20。

Daily全部來源列先驗25string、日期／code唯一及非空name；ALL7×20＝140selected rows的3500原strings／3080金融int64與七組買−賣＝net、外資／dealercomponents及total關係全驗，不能只驗目前所選股或外推其他股金融coverage。Selected investor原欄以0-based索引：foreign買／賣／net＝3／4／5（不含外資自營商）、trust＝12／13／14、dealer＝21／22／23（自行＋避險總）；驗components不換foreign口徑。

Canonical單位股，integer string傳遞；gross買／賣為非負int64，net為signed int64，張精確÷1000、既有單位公式不改。每日、buy／sell／net三種running prefix與ALL84gross＋42net window totals均須exact計算且在int64範圍：0～9223372036854775807（gross）／−9223372036854775808～9223372036854775807（net）；期末prefix與獨立window sum對帳，buy−sell＝net。每一5／20窗口buy／sell／net均從第一日前0起算，5不延用20prefix。任一daily／prefix／total、完整性／pins／來源關係不合使whole7profile failclosed，unknown／missing不補0或縮窗。

每point-date-row保ALL25原string／原ordinal／bodySHA／ORIGINALreceiptSHA及全部calendar原列。fresh有gross0cell且ALL7完整gate成立才可驗actualzero，fixture不代真值；ALL84窗口gross totals均非0，不稱actual零窗口。old daily net不重計。

## 44. M1-CHIPS-STOCK-SCOPE-7-DIRECTION-SEGMENTS-20-1006-20261008-1/B1：七股方向、計數與窗口區段

2026-10-08。ROOT已有限接受新來源／數值與具名操作。本節只管理新namespace；oldnet／oldgross／defaultpins與四TWSE profiles不改。操作見[個股頁 §49](STOCK_RESEARCH_PAGE.md)，入口見[開發入口](development-baseline/README.md)。

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

[REST11391](https://data.gov.tw/api/v2/rest/dataset/11391)／[REST11856](https://data.gov.tw/api/v2/rest/dataset/11856)已核ownerTPEx、license1、free、CSV UTF-8；OGL 1.0 與 TPEx 條款核對同 [§13.1](#131-獨立-policy-與四用途)。僅授本地RAM方向用途。完整canonical署名逐字如下：

> 財團法人中華民國證券櫃檯買賣中心（Taipei Exchange, TPEx）[2026] 櫃買指數歷史資料（dataset11391；dataset-11391-month-csv-observed-2026-10-08/chips-direction-segments-stock-scope-7-v1）及上櫃股票三大法人買賣明細資訊（dataset11856；dataset-11856-dated-csv-observed-2026-10-08/chips-direction-segments-stock-scope-7-v1）。此開放資料依政府資料開放授權條款（Open Government Data License）進行公眾釋出，使用者於遵守本條款各項規定之前提下，得利用之。政府資料開放授權條款－第1版：https://data.gov.tw/license。原欄、來源及完整性保留；方向與區段為本地衍生結果。

Published／firstavailability／revision未知、nonPIT，metadata時間不代金融row發布或決策時可知；磁碟保存／跨程序／正式DB／交易未授。

### 44.3 Finite FIRST及完整日曆

ONE NEW empty distinct producer，無seed／preload；trustedFIRST_once先2index月CSV，再完整calendar驗證後last20的20daily，總22GET，失敗亦SPENT；retry／redirect／probe／warmup0。只RAM保存ALL22 ORIGINAL bodies及未增補canonical receipts，不重造receipt、重開producer或重用舊capture。切股／套用／back／heldREAD不另fetch，cachedcapture409。上限同 [§31.3](#313-一次取得與可證執行上限)，diagnostic16MiB；原件／產物／privateIO／DB／priceGET均受本B1有限gate約束。

全部返回calendar原6欄先驗unique日期／requested month／weekday／nonclosed／≤observation／finite positiveOHLC及上下界，再與採入完整weekday集合扣[9/25、9/28公告](https://www.tpex.org.tw/storage/eb_data/11509/11503027221.html)對帳；不硬定returned25或從缺列推休市。合法postcutoff原列保留追溯但不採。此次25returned→24adopted→last20為9/07～10/06，last5為9/30、10/1、10/2、10/5、10/6；10/7保原欄excluded。Index calendar不代ordinary closes／MA20。

### 44.4 原欄、分類、counts與segments

全部daily來源列先驗25strings／日期／code唯一／非空name；ALL140selected的3500strings／3080金融int64及買−賣、components／total關係完整核。Foreign原net欄5不含外資自營商、trust14、dealer23為自行＋避險總（0-based）；原signed int64 canonical股數與精確股／張公式不改，unknown／missing不補0。

三net符號五類互斥且涵蓋27signcases：`all_positive`三正、`all_negative`三負、`opposite`至少一正一負且可含零、`single_direction_with_zero`單一非零方向且含零、`all_zero`三個精確零。每investor×5／20窗口正負零counts總和＝窗口長度；segments按窗口交易日期順序為maximal同sign連續區段，完整覆蓋一次、無重疊／缺口／相鄰同sign，zero獨立且終止正負run。Latest run僅最後一段，首段earlier_unknown=true，不以較長窗口或完整歷史外推更早日數。任一來源／pins／結構／數值／分類／區段不合，whole7profile failclosed，不縮窗或跳壞股。

Segment-date展開三原net、ALL25原strings／header／ordinal／bodySHA／ORIGINALreceiptSHA及完整calendar。Actualzero只由fresh原net精確0證明；derived count=0須逐原列predicate核，fixture不補實件。actual all-zero triple／整窗zero run／latest zero無實件，驗收缺口保留，不以fixture聲稱通過。

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/SOURCE_REGISTRY.md` §44.5。

## 45. M1-CHIPS-STOCK-SCOPE-7-ADJACENT-WINDOWS-5-1006-20261008-1/B1：兩相鄰5日比較與新來源准入

2026-10-08。ROOT有限接受新來源／數值與具名比較操作；本節只管理新namespace，old series／gross／direction／defaultpins及四TWSE profiles immutable。操作見[個股頁 §50](STOCK_RESEARCH_PAGE.md)，驗證入口見[開發入口](development-baseline/README.md)。

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

[REST11391](https://data.gov.tw/api/v2/rest/dataset/11391)／[REST11856](https://data.gov.tw/api/v2/rest/dataset/11856)之ownerTPEx／license1／free／CSV UTF-8／exact resource及header已核；OGL 1.0 與 TPEx 條款核對同 [§13.1](#131-獨立-policy-與四用途)，只授有限local RAM comparison、nondurable用途。685 UTF-8 bytes canonical署名逐字如下，不沿用舊686B：

> 財團法人中華民國證券櫃檯買賣中心（Taipei Exchange, TPEx）[2026] 櫃買指數歷史資料（dataset11391；dataset-11391-month-csv-observed-2026-10-08/chips-adjacent-windows-stock-scope-7-v1）及上櫃股票三大法人買賣明細資訊（dataset11856；dataset-11856-dated-csv-observed-2026-10-08/chips-adjacent-windows-stock-scope-7-v1）。此開放資料依政府資料開放授權條款（Open Government Data License）進行公眾釋出，使用者於遵守本條款各項規定之前提下，得利用之。政府資料開放授權條款－第1版：https://data.gov.tw/license。原欄、來源及完整性保留；相鄰窗口比較為本地衍生結果。

Observation10/08不代金融列發布或10/06決策時可知；published／firstavailability／revision未知、nonPIT。磁碟保存／跨程序／正式DB／交易未授，MIT軟體license不代dataRights。

### 45.3 Finite FIRST與完整日曆

ONE NEW empty distinct generation，seed0／preload=false，trusted FIRST_once先2index再全部calendar驗證後動態10daily，總12GET；失敗亦SPENT，retry／redirect／probe／warmup0。只RAM保存ALL12 ORIGINAL bodies及未增補canonical receipts；不能重造receipt、重開producer或reuse released capture。Apply／切股／back／held READ不新增來源，cachedcapture409。上限同 [§31.3](#313-一次取得與可證執行上限)，但aggregate22MiB、總12GET；diagnostic16MiB。原件、privateIO／DB／ordinaryprice GET及落盤產物受本B1有限gate約束。

全returnedcalendar每列原6欄先驗unique日期／requested month／weekday／nonclosed／≤observation、finite positive OHLC及上下界，再與完整weekday集合扣[9/25、9/28休市公告](https://www.tpex.org.tw/storage/eb_data/11509/11503027221.html)對帳；[交易規則](https://www.tpex.org.tw/zh-tw/mainboard/trading/rules/system.html)只支持本輪已核weekday條件。不硬25rows或從缺列推休市；合法postcutoff列保原件但不採。此批26returned→≤10/06 exact24adopted→last10 split5／5：前5為9/21、9/22、9/23、9/24、9/29，近5為9/30、10/1、10/2、10/5、10/6；10/7及10/8保原欄excluded。Index calendar不代ordinary closes／MA20。

### 45.4 原欄、窗口及positional pair計算

全部daily來源列先驗25strings／日期／code唯一／非空name；ALL7×10=70selected、1750原strings／1540金融int64及ALL22欄buy-sell-net、foreign／dealer components／total關係全驗，才可available。Foreign原net5不含外資自營商、trust14、dealer23為自行＋避險總（0-based）；canonical signedint64股數及精確股／張規則沿既有契約，本輪每個加減／窗口sum步／pair與total delta步均檢overflow。

每investor各5窗positive／negative／zero predicates互斥，counts總和=5；兩窗net各為五原net之和，count delta及net delta均為近5減前5。Maximal同sign連續segments完整覆蓋各窗一次、無gap／overlap／相鄰同sign；zero獨立且終止正負run。Latest僅各窗末段，首段earlier_unknown=true，不外推完整歷史。

每股5 positional pairs依前窗第1～5日配近窗第1～5日，兩個不同日期而非同日比較。Each pair delta=recent原net−previous原net，五pair delta之和=window net delta；每股三investor共21net deltas／63count deltas，35pairs×3=105pair deltas精確核。每pair保兩列ALL25原strings／header／ordinal／bodySHA＋ORIGINALreceiptSHA／三net及全returnedcalendar。Daily net0、統計count0、窗口sum0、delta0各有不同predicate，不把missing或unknown當0；任一來源／pins／calendar／結構／數值／pair conflict，whole7 failclosed，不跳壞股或縮窗。actual all-zero triple／整窗全零／net sum0／total delta0／pair delta0均無實件，缺口保留，fixture不充真值。

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/SOURCE_REGISTRY.md` §45.5。

## 46. M1-CHIPS-STOCK-SCOPE-7-DEALER-COMPONENTS-5-1006-20261008-1/B1：自行買賣、避險與合計來源及對帳

2026-10-08。ROOT有限接受具名actual對帳，操作見[個股頁 §51](STOCK_RESEARCH_PAGE.md)，驗證入口見[開發入口](development-baseline/README.md)。本節只管理新namespace，old series／gross／direction／adjacent／defaultpins與四TWSE profiles immutable。

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

OGL 1.0 與 TPEx 條款核對同 [§13.1](#131-獨立-policy-與四用途)；本批另核官方[dataset11391](https://data.gov.tw/dataset/11391)／[dataset11856](https://data.gov.tw/dataset/11856) HTML 與 TPEx English terms：provider金融監督管理委員會證券期貨局（FSC SFB）、ownerTPEx、free CSV／license1／exact resource links、OGL1完整notice及TPEx English §7政府開放資料例外／§5一般下載限制。只有有限local RAM dealer-components比較用途；weekday／9/25、9/28 closure規則沿§45，不沿用舊financial calendar或capture。

本worker774 UTF-8 bytes完整署名逐字如下（不是前批685B）：

> 金融監督管理委員會證券期貨局提供、財團法人中華民國證券櫃檯買賣中心（Taipei Exchange, TPEx）[2026] 櫃買指數歷史資料（dataset11391；dataset-11391-month-csv-observed-2026-10-08/chips-dealer-components-stock-scope-7-v1）及上櫃股票三大法人買賣明細資訊（dataset11856；dataset-11856-dated-csv-observed-2026-10-08/chips-dealer-components-stock-scope-7-v1）。此開放資料依政府資料開放授權條款（Open Government Data License）進行公眾釋出，使用者於遵守本條款各項規定之前提下，得利用之。政府資料開放授權條款－第1版：https://data.gov.tw/license。原欄、來源及完整性保留；自行買賣、避險及總額之每日與五日比較為本地衍生結果。

Metadata觀測不代金融列publication／firstavailability／revision，三者仍unknown、nonPIT；統計依原成交、未含券商帳戶更正。磁碟保存／跨程序／正式DB／交易未授，MIT軟體license不代dataRights。

### 46.3 Finite FIRST與全calendar

ONE NEW empty distinct producer，seed0／preload=false；明示trusted FIRST_once先2index，全部returnedcalendar原6欄先驗requested month／unique日期／weekday／nonclosed／≤observation、finite positive OHLC與上下界及finite漲跌，再將≤cutoff採入日期與完整weekday扣已核9/25、9/28休市對帳，才fresh derive last5、動態5daily。失敗亦SPENT；retry／redirect／probe／warmup／preload0，不硬26或舊dates。合法postcutoff保原列excluded；index calendar不代ordinary closes。

Exact GET sequence：本新index base URL `https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?response=data`，加percent-encoded Gregorian `date=2026/09/01`及`2026/10/01`；再新daily base URL `https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data`加各derived日期percent-encoded ROC `d`。Body空、HTTP200／identity／UTF-8 CSV，完整ALL7 ORIGINAL bodies及未增補canonical receipts只RAM；不以receipt重造或released capture作seed。上限同 [§31.3](#313-一次取得與可證執行上限)，但最多7 requests／aggregate12MiB；diagnostic16MiB。

### 46.4 ALL25原欄與每日／窗口計算

全部daily先驗25原strings／date／code唯一／name及ALL7 identity／missing，selected35×25=875strings、35×22=770金融int64全部合格後才available。Canonical signed-int64股數、gross非負、每buy−sell=net，ALL22／七buy-sell-net triplets／foreign components／dealer components／三法人合計關係完整核，不只取三組顯示欄。任一來源／pins／calendar／結構／數值／identity conflict則whole7 unavailable，不跳壞股／補0／縮窗。

| Dealer component | 0-based買／賣／淨額 |
| --- | --- |
| 自行買賣 self | 15／16／17 |
| 避險 hedge | 18／19／20 |
| 合計 total | 21／22／23 |

Each day及window，每metric self＋hedge=total、buy−sell=net；三組buy／sell／net各自按本fresh5順序累加，everycomponent addition／subtraction及每sumstep檢signed-int64。股／張精確÷1000、至多3 decimals，不以float或圖形約值對帳。每列保ALL25原strings／header／ordinal／bodySHA／未增補ORIGINALreceiptSHA／URL與9component metrics；全returnedcalendar原欄可追溯。Zero predicates只針對合格原數值，missing／unknown不當0。window zero／triple zero／net zero缺實件未驗，fixture不補actual；無save／cross-process／ranking／filter／price／Signal／Plan或完整M1外推。

### 46.5 本次actual與未驗

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/SOURCE_REGISTRY.md` §46.5。

## 47. #36 qa1／qa2：七股 TPEx 法人六日 dated CSV 與兩截止五日分子（issue36-two-cutoffs-v1）

2026-10-11。#36 以政府 [dataset11856](https://data.gov.tw/dataset/11856) 的 TPEx dated CSV 取得七股六個日期的法人原件，供 2026-10-05、2026-10-06 兩個截止日各含截止日向前五個交易日的三法人淨股數與合計 consumer（產品 `backend/app/tpex_institutional_five_day_source.py`，測試 `backend/tests/test_tpex_institutional_five_day_source.py`）。本節只管理這個新 namespace，不提升也不改寫其他節的 policy、pins、capture 或 default；六個日期由外部 policy 固定、不由日曆推導，本單不取日曆與 metadata（requests 0）。取得過程與 QA 收據保存在 [#36](https://github.com/YiCheng0608/stock-lab/issues/36)；額度、seal、防護性質與署名的共同規則見 [FinMind 來源共同規則](#finmind-來源共同規則)。

### 47.1 版本、外部 pins 與上限

| 項目 | 內容 |
| --- | --- |
| 外部 policy | version `issue36-tpex-institutional-six-days-two-cutoffs-2026-10-10.1`；canonical 7,500 UTF-8 bytes（sorted keys、compact JSON、無尾 LF）；SHA-256 `93d8e746eccbed035d5a79ffbf178b5f89877017c2aea69e6b841d178c1b51a3`，由全局獨立生成 |
| namespace | 產品只接受 `issue36-seven-institutional-five-day-two-cutoffs-v1/qa2`；qa1 namespace 與其 source-use 收據值被 `seal_scope_conflict` 拒絕 |
| profile／source | profile `free_public_local_ram_institutional_two_cutoffs_v1`；source id `tpex_government_institutional_csv`，version `dataset-11856-dated-csv/issue36-two-cutoffs-v1`；provider 金融監督管理委員會證券期貨局（FSC SFB），owner 財團法人中華民國證券櫃檯買賣中心（TPEx） |
| consumer | `institutional-five-day-net-summary-two-cutoffs-v1`：7 個 getter、14 個 summary（兩截止 × 七股）、42 個類別合計 |
| 標的與日期 | TPEx 3105／3293／5274／5347／6488／6510／8069；2026-09-29、09-30、10-01、10-02、10-05、10-06 |
| 請求 | 固定 6 個 GET：`https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php`，query 依序 `l=zh-tw`、`se=EW`、`t=D`、`o=data`、`d=<民國日期，如 115%2F09%2F29>`；不換 provider、日期或路由 |
| 上限 | 每份 body 1 MiB、aggregate raw 6 MiB、retained-roots estimate 32 MiB；每 URL 20 s、整批 180 s；其餘同共同規則 |

### 47.2 用途、授權與署名

用途只限免費公開、本地盤後研究與 RAM 取得／驗證／consumer。Policy `uses`：`local_fetch` 只對本單六個請求、須先有 fresh seal；`raw_store` 只在 RAM；`disk_store`、`raw_publish`、`commercial_use` 不准入；`historical_pit` 不支援。統計基準為原成交、未含券商帳戶更正，單位為股。OGL 1.0 與 TPEx 條款核對同 [§13.1](#131-獨立-policy-與四用途)；完整署名見 [§47.7](#477-完整署名)。

只對這六個日期、七股、這個來源與本地 RAM 用途有效，官方查詢 SLA 未知。Policy 明列不支援：PIT、publication、first availability、revision lineage、adjustment、20 日成交值分母、`shares ÷ TWD` 的無因次策略門檻、完整歷史成員、hot group、strategy、Signal、Plan、API、UI、DB、cross-process，以及其他日期、路由與 provider；`denominator`、`amount`、`strategy`、`historical_pit` 在 consumer 皆為 `unsupported`。

### 47.3 原件驗證與五日分子計算

- **取得**：HTTP 200、identity encoding（無 `content-encoding`），完整 EOF 與 raw hash 通過後才 parse；body 恰達上限時須由既有 framing 讀到 EOF 才接受，未知長度達上限則直接拒絕，不做 +1 或 read(0) probe。
- **標頭**：`content-length`、`transfer-encoding`、`content-encoding`、`content-type` 任一重複即 fail-closed，失敗碼 `duplicate_response_header:<小寫標頭名稱>`；其他標頭重複（如 `cache-control`、`vary`、`set-cookie`）接受，結果與無重複相同。診斷與輸出只含標頭名稱與次數，不含值；不送出、不使用、不保存 cookie。
- **CSV**：strict UTF-8、無 BOM、stdlib `csv` strict；25 欄 header 與 policy 逐欄相符；日期為 7 位民國日期且等於請求日；代號符合 `[0-9A-Z]{4,6}` 且唯一、名稱非空。全部回傳列都驗結構，未選列以有界暫存串流處理；七股各取一列，得 42 列、1,050 原字串、924 個金融整數（42 × 22）。
- **整數**：canonical ASCII 整數字串，signed int64（絕對值至多 `9223372036854775807`）；買進與賣出非負，每組買 − 賣 ＝ 淨額；外資及陸資 ＝ 外資（不含外資自營商）＋ 外資自營商；自營商 ＝ 自行買賣 ＋ 避險；三大法人合計 ＝ 外資（不含外資自營商）＋ 投信 ＋ 自營商。
- **窗口與合計**：類別淨額取 0-based 欄位 5（外資及陸資，不含外資自營商）、14（投信）、23（自營商，自行買賣 ＋ 避險），合計取欄位 24；外資自營商不重複計入。窗口含截止日向前五個固定日期：2026-10-05 為 09-29、09-30、10-01、10-02、10-05；2026-10-06 為 09-30、10-01、10-02、10-05、10-06，10-06 的列不進 10-05 窗口。六份原件須全部取得並合格才有結果，不補 0、不縮窗；每個加減步檢 signed int64 界限。結果單位為股，以 canonical 整數字串表示。

兩截止日的三類淨股數與合計（本地衍生結果，單位：股，每列三類之和等於合計）。2026-10-05 如下表；2026-10-06 的五日值同 [§31.4](#314-12-net-金融真值)（3105／6488）與 [§37.2](#372-actual原件與42個精確窗口值) 的 5 日欄（其餘五股），不重列：

| 2026-10-05 | 外資及陸資（不含外資自營商） | 投信 | 自營商（自行買賣＋避險） | 合計 |
| --- | ---: | ---: | ---: | ---: |
| 3105 | 28,396,840 | 2,812,800 | 2,350,894 | 33,560,534 |
| 3293 | 6,386,218 | 414,000 | -12,792 | 6,787,426 |
| 5274 | -28,586 | -40,427 | 10,254 | -58,759 |
| 5347 | 323,290 | 3,600,607 | 339,261 | 4,263,158 |
| 6488 | 354,337 | 1,179,529 | -62,262 | 1,471,604 |
| 6510 | 186,887 | -594,227 | 32,887 | -374,453 |
| 8069 | -4,247,384 | -13,040 | 64,380 | -4,196,044 |

窗口和為零未出現，該情形只有合成證據；真實資料的負向（壞欄、缺列）與 401、403、429 路徑只有合成證據。

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/SOURCE_REGISTRY.md` §47.4、§47.5、§47.8。

### 47.6 qa2：成功取得與驗證結果

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/SOURCE_REGISTRY.md` §47.6。兩截止日五日淨額表現行見 [§47.3](#473-原件驗證與五日分子計算)。

### 47.7 完整署名

609 UTF-8 bytes，與外部 policy 的 `rights.attribution` 及 QA 收據末段逐字相同：

> 金融監督管理委員會證券期貨局提供、財團法人中華民國證券櫃檯買賣中心（Taipei Exchange, TPEx）[2026] 上櫃股票三大法人買賣明細資訊（dataset11856；dataset-11856-dated-csv/issue36-two-cutoffs-v1）。此開放資料依政府資料開放授權條款（Open Government Data License）進行公眾釋出，使用者於遵守本條款各項規定之前提下，得利用之。政府資料開放授權條款－第1版：https://data.gov.tw/license。原欄、來源及完整性保留；2026-10-05與2026-10-06各五日三法人淨股數及合計為本地衍生結果。

## 48. #31 qa1／qa2／qa3：七股 FinMind 融資餘額與兩截止五日變動比（ordinary-margin-cutoffs-1005-1006-v2）

2026-10-12。#31 以 FinMind `TaiwanStockMarginPurchaseShortSale` 取得七股 2026-09-24～2026-10-09 的融資原件，供 2026-10-05、2026-10-06 兩個截止日各含截止日向前五個間隔（六個交易日）的 `MarginPurchaseTodayBalance` 變動比 consumer（產品 `backend/app/tpex_margin_balance_source.py`，測試 `backend/tests/test_tpex_margin_balance_source.py`）。本節只管理這個新 namespace，不提升也不改寫其他節的 policy、pins、capture 或 default；日曆用 [§31.2](#312-24日完整觀測日曆與20日金融集合)的已驗交易日，不由日曆推導。取得過程與 QA 收據保存在 [#31](https://github.com/YiCheng0608/stock-lab/issues/31)；共同規則見 [FinMind 來源共同規則](#finmind-來源共同規則)。

### 48.1 版本、外部 pins 與上限

| 項目 | 內容 |
| --- | --- |
| 外部 policy | schema `ordinary-margin-source-policy/v2`；canonical 2,886 UTF-8 bytes（sorted keys、compact JSON、無尾 LF）；SHA-256 `7d8cd5b1835b84138e2bc982d86a93d4b3b4a3bba809842341c279fe566a9ceb`，由全局發布。AC 修訂 2（FinMind-only）起產品只接受 v2；policy v1（qa1、qa2 的 TPEx 官方 CSV＋FinMind 方案）的文字與 pin 不再被接受，產品不含任何 TPEx 官方件 |
| source／consumer | provider FinMind，dataset `TaiwanStockMarginPurchaseShortSale`；consumer `ordinary-margin-change-ratio-v1`，version `ordinary-margin-cutoffs-1005-1006-v2`：14 個 consumer（兩截止 × 七股），每個含 6 個 `MarginPurchaseTodayBalance` |
| namespace | 產品只接受 `issue31-margin-seven-cutoffs-1005-1006-v1/qa3`（字串中的 `v1` 是 namespace 名稱，不是 policy 版本）；qa1、qa2 namespace 的值被拒絕 |
| 標的與日期 | TPEx 3105／3293／5274／5347／6488／6510／8069；請求範圍 2026-09-24～2026-10-09；已驗交易日 2026-09-24、09-29、09-30、10-01、10-02、10-05、10-06（09-25、09-28 為閉日） |
| 窗口 | 2026-10-05：09-24、09-29、09-30、10-01、10-02、10-05；2026-10-06：09-29、09-30、10-01、10-02、10-05、10-06 |
| 請求 | 固定 7 個 GET，依上列標的次序：`https://api.finmindtrade.com/api/v4/data`，query 依序 `dataset=TaiwanStockMarginPurchaseShortSale`、`data_id=<代號>`、`start_date=2026-09-24`、`end_date=2026-10-09`；標頭只有 `Accept-Encoding: identity` 與 `User-Agent: stock-lab-issue31-local-ram/1`（stdlib 另加 `Host`）；不換 provider、日期或路由 |
| 上限 | 每份 body 1 MiB、aggregate raw 8 MiB、retained-roots estimate 32 MiB；每 URL 20 s、整批 180 s；其餘同共同規則 |

### 48.2 用途、授權與署名

用途只限免費公開、個人非商用、本地盤後研究與 RAM 取得／驗證／consumer。Policy `supportedUse`：`local_personal_noncommercial`、`process_ram_snapshot`、`margin5_balance_change_ratio`；`unsupportedUse`：`historical_pit`、`publication_time`、`first_availability`、`revision_history`、`historical_eligibility`、`historical_membership`、`actionable_strategy`、`plan`、`trading`、`disk_raw_storage`、`raw_redistribution`、`mirror`、`deployment`、`other_cutoff`、`official_unit_verification`。產品的 `UseRequest` 只接受預設值，其餘用途一律 `unsupported_use`。FinMind 是服務提供者，不是官方直接來源；完整署名見 [§48.6](#486-完整署名)。

只對這七股、這兩個截止日、這個 dataset 與本地 RAM 用途有效；TWSE、其他市場、其他 cutoff、PIT、策略、Plan、API、UI、DB、cross-process 均不支援。餘額與比值只在 RAM 驗證、沒有保存，不產生可供其他功能取用的資料；單位「張」只有 FinMind 內部一致性（鏈式、日期集合）支持，沒有官方 anchor；`Note` 缺欄與 `null`、到期後拒用與失敗路徑清除只有合成證據；匿名成功不證匿名額度、限流或 FinMind 的長期穩定。

### 48.3 原件驗證與五日變動比計算

- **取得**：只接受 HTTP 200（其他狀態含 redirect 一律拒用，出現 `location` 即 `http_redirect`）、identity encoding（無 `content-encoding`，或其值為 `identity`），媒體型別 `application/json`（可帶 `charset=utf-8` 或 `charset="utf-8"` 參數，其他參數與媒體型別拒用）；完整 EOF 與 raw hash 通過後才 parse。`content-length`、`transfer-encoding`、`content-encoding`、`content-type`、`location` 任一重複即 fail-closed，其他標頭重複（如 `cache-control`、`vary`、`set-cookie`）不影響結果；不送出、不使用、不保存 cookie。以 stdlib 直接建立連線；`http.client.HTTPSConnection` 被替換時以 `transport_class_replaced` 在花用額度前拒用，稽核須以 `connection_factory` 組合包裝。
- **JSON 與 envelope**：strict UTF-8、無 BOM（BOM 以 `bom_rejected` 拒用）；envelope 恰為 `msg`、`status`、`data` 三鍵，`status` 為 200、`msg` 為 `"success"`，`data` 為 1～10,000 列。
- **列結構**：FinMind 文件的 16 欄中，必要 15 欄（`date`、`stock_id` 為字串，其餘 13 欄為 0 至 int64 上限的非 bool 整數）；`Note` 可選（缺欄、`null` 或至多 256 字元的字串），不進任何計算；任何其他鍵拒用。`date` 只收 ISO `YYYY-MM-DD`、落在 2026-09-24～2026-10-09 且唯一；`stock_id` 等於請求代號。
- **內部一致性**（取代官方 anchor）：每股依日期排序後，到 2026-10-06 的日期恰為七個已驗交易日；2026-10-06 之後至少有一列；相鄰列 `MarginPurchaseYesterdayBalance[i+1] == MarginPurchaseTodayBalance[i]`（含 10-06 之後的連結）；七股的日期集合相同。2026-10-06 之後的列只作鏈式核對，不進任何窗口。任一不符整批拒用，不補值、不縮窗。
- **單位**：「張」（lots）、scale 1 是明示的 provider 推論（`providerLiteral=false`、`officialAnchorVerified=false`），沒有官方 anchor 驗證。
- **計算**：每股每窗口取 6 個 `MarginPurchaseTodayBalance`，變動比 `(B[T]-B[T-5])/abs(B[T-5])`，以整數分子與正分母（`abs(B[T-5])`）表示；門檻 `<= 0.05` 以精確整數比較 `20*分子 <= 正分母`，四捨五入的顯示值不進閘門；分母為 0 則整批拒用。公式與門檻與正式 canonical（`backend/worker/pipeline.py` `_margin_change_ratio`、`backend/app/domain.py` `maximum_balance_change_ratio`）一致；差異只在產品用精確整數／`Fraction`，canonical 用浮點。

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/SOURCE_REGISTRY.md` §48.4、§48.5、§48.7。

### 48.6 完整署名

273 UTF-8 bytes，與產品常數 `ATTRIBUTION` 逐字相同：

> FinMind: TaiwanStockMarginPurchaseShortSale; local personal noncommercial RAM snapshot only; no raw redistribution/mirror. FinMind is the service provider; this is not an official direct feed and the lot unit is an explicit provider inference, not an official verification.

## 49. #32 qa1／qa2：七股 FinMind nominal OHLCV 日線 last60 與兩截止 raw 算術（issue32-seven-nominal-ohlcv-two-cutoffs-v1）

2026-10-12。#32 以 FinMind 公開 API v4 取得七股 2026-07-01～2026-10-06 的 provider-reported nominal OHLCV 日線與 FinMind 交易日，供 2026-10-05、2026-10-06 兩個截止日各取「截止日（含）向前 60 個交易日」的 last60 getter，以及 `ordinary-nominal-ohlcv-window-summary-v1` raw 算術 snapshot consumer（MA20／MA60 收盤、prior20 最高價、prior20 成交量與成交值平均）。產品 `backend/app/ohlcv_history_source.py`，測試 `backend/tests/test_ohlcv_history_source.py`。本節只管理這個新 namespace，不提升也不改寫其他節的 policy、pins、capture 或 default；「交易日以來源實際回傳為準、不限天數」只適用本 namespace，不回溯其他節已驗的日曆契約（例如 §13 的 9/25、9/28 公告）。取得過程與 QA 收據保存在 [#32](https://github.com/YiCheng0608/stock-lab/issues/32)；共同規則見 [FinMind 來源共同規則](#finmind-來源共同規則)。本節不含任何取回的價格列、原始 body 或衍生數值；它們只在 RAM，已隨 qa2 的 release 清除。

### 49.1 版本、外部 pins 與上限

| 項目 | 內容 |
| --- | --- |
| 外部 policy | version `issue32-ordinary-nominal-ohlcv-history-seven-cutoffs-v3`；canonical 4,766 UTF-8 bytes（sorted keys、compact JSON、無尾 LF）；SHA-256 `2f454a9aa51b70db331e867ffdb3cf3391a45e238e55cf885fe4396e34b86b91`，由全局發布。產品只接受 v3 與 namespace `issue32-seven-nominal-ohlcv-two-cutoffs-v1/qa2`；v1（3,266 B，SHA-256 `0f8c95eca6f0dcd08ca9b874996c4f41f8f8cf356f3282fee1e1c3f23734292d`，TPEx 7 月日曆 CSV＋FinMind 價格）、v2（3,497 B，SHA-256 `076e36f2c3bb3169866fc728e155e99886e084871480810f2cda6f54aff1eaba`，未進入真實 run）與 qa1 namespace 的值都被拒絕 |
| profile／用途 | profile `free_public_local`；source_use `local_personal_noncommercial_observed_nominal_ohlcv_snapshot`；market TW/TPEx、ordinary stock、identity_as_of 2026-10-06；basis `provider_reported_nominal_ohlcv`；consumer `ordinary-nominal-ohlcv-window-summary-v1` |
| 來源 | FinMind。交易日 dataset `TaiwanStockTradingDate`，version `finmind-trading-dates-checked-against-formal-aug21-sep20-oct4/issue32-v3`，每列只有 `date`。價格 dataset `TaiwanStockPrice`，欄位 open→`open`、high→`max`、low→`min`、close→`close`、volume→`Trading_Volume`、amount→`Trading_money` |
| 標的與日期 | 3105 穩懋／3293 鈊象／5274 信驊／5347 世界／6488 環球晶／6510 精測／8069 元太；區間 2026-07-01～2026-10-06；cutoff 2026-10-05、2026-10-06 |
| 請求 | 固定 8 個 GET，host 只有 `api.finmindtrade.com`，endpoint `https://api.finmindtrade.com/api/v4/data`。#0 交易日：`?dataset=TaiwanStockTradingDate&start_date=2026-07-01&end_date=2026-10-06`。#1～#7 價格：七股依 3105、3293、5274、5347、6488、6510、8069 升序，`?dataset=TaiwanStockPrice&data_id=<code>&start_date=2026-07-01&end_date=2026-10-06`（query 依序 dataset、data_id、start_date、end_date）。交易日先取，通過 gate 才取價格；不換 provider、日期或路由 |
| 請求標頭 | 明設四個：`Accept-Encoding: identity`、`Connection: close`、`User-Agent: stock-lab-issue32-local-ram/1`、`Accept: application/json`；另有 `http.client` 依 URL 自動加的 `Host`（qa2 的請求逐位元組核對涵蓋它）；不帶 token、cookie、proxy |
| 上限 | 每份 body 1 MiB（1,048,576 B）、aggregate raw 8 MiB（8,388,608 B）、retained-roots estimate 32 MiB（33,554,432 B）；每 URL 20 s、整批 180 s；其餘同共同規則 |
| 固定 formal 參照 | formal 45 日與 §32.2 的 42 個 anchor 由產品從固定 blob `d8918bc6491ec8ef65874979cf88d1322df2da43:docs/SOURCE_REGISTRY.md`（268,729 B；SHA-256 `b5ea9605c75add4bfa5581672d3778ac2851a29ac599e3e0b9e938880f42abde`）的 §19.2、§31.2、§32.2 解析。呼叫者必須提供該 blob，位元組不符即 `formal_blob_pin` 拒絕。這個 pin 指向 commit 內容，不隨本檔後續編修而變，也不能改指目前工作樹的檔案 |

### 49.2 用途、授權與署名

用途只限免費公開、本地個人非商用研究與 RAM 取得／驗證／consumer。Policy 的 `unsupported` 含 `raw_disk_storage` 與 `redistribution`，storage 只有 process RAM；不落盤、不發布 raw、不鏡像。權利字串（policy `rights`，逐字）：`FinMind personal noncommercial local RAM; attribution; no raw redistribution or mirror`；署名方式見 [FinMind 來源共同規則](#finmind-來源共同規則)。「交易日以實際開市紀錄驗證、不限定天數」與「資料以 FinMind 為主、不再取 TPEx CSV」是使用者決策，保存於 #32。

免費使用是文件推論，不是明示陳述。FinMind 文件（`finmind.github.io`）把 `token` 列為選填，無 token 流量上限 300 次／小時（有 token 600）；受限資料集的標題都帶「只限 backer、sponsor 會員使用」等標記，`TaiwanStockTradingDate` 與 `TaiwanStockPrice` 沒有，但文件沒有寫「可免 token」。Policy 因此規定 401、402、403 或任何要求付費、登入的回應是首敗。

### 49.3 原件驗證與 last60／summary 計算

- **取得**：HTTP 200 才接受；401、402、403 或任何要求付費、登入的回應是首敗。body 須 identity 或無 `content-encoding`（gzip、br 拒）；`content-type` 為 `application/json`，大小寫不拘，可接 `; charset=utf-8`，其他值與缺少一律拒。Framing 接受 content-length、chunked、close-delimited（讀到 EOF，受 1 MiB 限制）；content-length 與 chunked 並存拒，達上限仍無 EOF 拒。完整 EOF 與 raw hash 通過後才 parse；strict UTF-8、無 BOM。
- **標頭**：`content-length`、`content-encoding`、`transfer-encoding`、`content-type` 任一重複即拒；其他標頭重複接受並忽略；`set-cookie` 接受，不送出、不使用、不保存。
- **交易日**：回應須為 `{status:200, msg:"success", data:[…]}`；**全部回傳列**先驗結構（每列鍵恰為 `date`、合法 ISO 日期、唯一且遞增），之後才捨棄 2026-07-01～2026-10-06 以外的列，所以來源是否依 `start_date`／`end_date` 過濾都不影響結果。區間內的日期須全為平日、包含兩個 cutoff、各 cutoff（含）以前至少 60 個交易日，且 8～10 月部分與 formal 45 日（8 月 21 個、9 月 20 個、10 月至 10/06 共 4 個交易日）**完全相同**；8 月見 [§19.2](#192-全月驗證27日曆與八截止)，9、10 月見 [§31.2](#312-24日完整觀測日曆與20日金融集合)。不限定天數、不從缺列推休市、不縮窗；任何無法解釋的不一致整批拒，且發生在任何價格 GET 之前。
- **價格**：每檔回應須為 `{status, msg, data}`，`data` 列數等於交易日數 N；每列含 `date`、`stock_id`、`open`、`max`、`min`、`close`、`Trading_Volume`、`Trading_money`（可另含 `spread`、`Trading_turnover`，不採用）；`stock_id` 等於請求代號；日期唯一且屬交易日，**七股各自的日期集合都須與交易日集合完全相同**。OHLC 為有限正值且 high ≥ max(open, low, close)、low ≤ min(open, high, close)；成交量與成交值為正的 signed-int64 整數。OHLC、量或額為 0 的列一律拒收，整批停止，不補 0、不挑列。
- **單位**：composite mapping inference，scale 1：OHLC 為 TWD／股、成交量為股、成交值為 TWD。FinMind 沒有逐欄標示單位（policy `provider_literal_unit_annotation` 為 false），推論以 §32.2 在 2026-10-06 的 42 個 anchor（七股 × 開高低收量額六欄）逐值 exact 相等交叉驗證，含成交量與成交值。
- **admission**：獨立 oracle 的 admission 須等於 `(N, 7N, 42N, 42)`（交易日列數、價格列數、價格欄位數、anchor 欄位數），並綁定 8 份 receipt 的 SHA-256；real 路徑另綁定 QA holder、candidate 與 script SHA-256。取得完成後狀態為 pending，須通過 admission 才 available，getter 與 consumer 才可用；failed、expired（租約至多 180 s）與 released 都拒用。
- **last60**：`get_nominal_ohlcv60(snapshot, symbol, cutoff)` 取日期 ≤ cutoff 的最後 60 根，須恰 60 根且最後一根日期等於 cutoff。
- **summary**：`ordinary_nominal_ohlcv_window_summary_v1(snapshot, symbol, cutoff)` 的 `ma20_close` 為含 cutoff 的最後 20 根收盤平均，`ma60_close` 為 last60 收盤平均，`prior20_*` 取嚴格早於 cutoff 的 20 個交易日（須恰 20 根）：`prior20_high` 為最高價，`prior20_volume_mean`、`prior20_amount_mean` 為成交量與成交值平均。平均值為最簡整數有理數（分子／正分母），不用浮點、不做 context 捨入。
- **拒用**：purpose 非固定值回 `unsupported_purpose`；cutoff 不在兩個截止日或代號不在七股回 `unsupported_window_scope`；未傳 snapshot 回 `snapshot_required`；provenance 固定 `publication_time`、`first_availability`、`revision_time` 為 `unknown`，並列出 policy `unsupported`。
- **已觀測邊界**：qa2 取得的交易日區間內 N＝67（7 月 22、8 月 21、9 月 20、10 月 4），8～10 月 45 日與 formal 45 日完全相同；2026-07-10（週五）不在 FinMind 交易日，也不在七股任何一檔的價格資料，原因沒有證據，7 月沒有獨立於 FinMind 的第二來源。依交易日序列推得：2026-10-05 的 last60 從 2026-07-09 起、跨過這個缺口；2026-10-06 的 last60 從 2026-07-13 起，不含缺口。
- **不支援與已接受風險**：Policy 明列不支援 adjusted prices、公司行動、停牌可比性、全段 historical membership／eligibility、策略、Plan、交易、歷史模擬、raw 落盤、再散布及其他 cutoff；FinMind 無公告成交價的日子 OHLC 為 0 時整批拒收、不補 0、不縮窗（停牌不支援）；gzip、br 回應被拒；免費使用是文件推論，限流與條款日後可能改變。租約 expiry、chunked／close-delimited／quoted charset／非身分標頭重複／`set-cookie`、401／402／403 與零價列的真實路徑未觸發，只有 RAM 重放證據。

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/SOURCE_REGISTRY.md` §49.4、§49.5。

### 49.6 qa2：成功取得與驗證結果

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/SOURCE_REGISTRY.md` §49.6。

### 49.7 未驗與限制

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/SOURCE_REGISTRY.md` §49.7。

## 50. #97：七股 TPEx 靜態規則表（tpex-static-rules/2026-10-12/v1）

2026-10-12。#97 為七檔 TPEx 普通股、盤後 long、最早 T+1 的模擬執行建立 tick、交易時段、賣方證交稅與手續費門檻的靜態規則表與讀用介面（[`backend/app/tpex_execution_rules.py`](../backend/app/tpex_execution_rules.py)，純標準函式庫，import 不開檔、不連網、不碰 DB 與設定）。只讀公開規則文件，不是金融取源，不需 seal；不取行情、不讀寫 DB。原件不進 repo，來源以 URL、擷取 UTC、bytes 與 SHA-256 識別。

### 50.1 版本與來源

規則版本 `tpex-static-rules/2026-10-12/v1`。C1 的擷取方式為單次 GET，不帶 cookie 與 token、不跟隨轉址（其他來源的擷取收據未載此細節）；`selaw` 是證基會彙編的法令查詢系統，**不是發布機關原件**，對各條沒有逐條生效日，只有版本發佈日。

| 代號 | 文件與發布機關 | URL | 擷取 UTC／bytes | SHA-256 | 版本日 |
| --- | --- | --- | --- | --- | --- |
| C1 | 證券商營業處所買賣有價證券業務規則（TPEx 訂定，現行法規）全文，selaw 彙編 | `https://www.selaw.com.tw/Chinese/RegulatoryInformationResult/Article?sysNumber=LW10812069&releaseDate=2026-10-05` | 2026-10-12T12:11:07Z／705,924 | `c1ddb12e0593a972ef4015b102e65e42ac37bdb186855772ea65ef51471e7d49` | 發佈日期民國 115-10-05 |
| B2a | 同上，現行版沿革頁（僅第 47 條，116-04-01 實施） | `https://www.selaw.com.tw/Chinese/RegulatoryInformationResult?sysNumber=LW10812069` | 2026-10-12T11:57:56Z／24,847 | `2225a9aeec0a42b2fa56162835b8ef84e12a5bbffb2711f356a6dd120aeccf46` | 民國 115-10-05 |
| B2b | 同上，第 55 條較早版本，selaw 彙編 | `https://www.selaw.com.tw/Chinese/LawDetail/LawArticleReference?lawDataid=13022101` | 2026-10-12T11:58:21Z／20,130 | `82f87349047a5173fdbf5a9e558a7956ce004d8130725b36b66e265d5a65642b` | 發佈日期民國 110-01-11 |
| B1 | TPEx 官網「上櫃有價證券交易系統簡介」 | `https://www.tpex.org.tw/zh-tw/mainboard/trading/rules/system.html` | 2026-10-12T11:57:32Z／24,696 | `fd1217d8ef6e8e48769b1e4c3d2aea3b4878148b53879fd33423555d03cb291f` | 頁面無版本日 |
| B5c | 證券商營業處所買賣有價證券管理辦法（金管會），全國法規資料庫 | `https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=G0400071` | 2026-10-12T12:03:20Z／50,983 | `e15be76abf1cb5d6be5f56c5f171511ef00e43c88783042277b35e01a95082a9` | 修正日期民國 106-03-31 |
| B4 | 證券交易稅條例（財政部），財政部主管法規共用系統 | `https://law-out.mof.gov.tw/LawContent.aspx?id=FL006079&kw=b&media=print` | 2026-10-12T11:57:48Z／37,019 | `e5f6388ea66efe64e295c0757d76d6a4c0b8dd4bbc5c6394065c9ff9d2793291` | 修正日期民國 114-01-02 |
| B6 | 同上，全國法規資料庫 | `https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=G0340078` | 2026-10-12T12:03:35Z／55,700 | `372ef60403bdfc4ff2108204562a209b7cf56975c99da40cf604802460bd0e48` | 修正日期民國 114-01-02 |
| B7 | 財政部臺北國稅局新聞稿（稅額算例，不是法規；僅示範成交價格×股數×3‰，算例情境為已簽證發行股票之未上市公司股權出售，非上櫃普通股集中交易） | `https://www.mof.gov.tw/%20/singlehtml/384fb3077bb349ea973e7fc6f13b6974?cntId=c29280e284a54c44a893e45b84f6efa5` | 2026-10-12T11:57:52Z／72,653 | `6a70c06754ac5d05a9ea4638fdcabbaef747e2d19c6d3b0f8526a6c69076fc66` | 發布 2026-03-10 |

模組內的 `source_id` 與代號對應：`tpex-rules-art35／art40／art55／art64-selaw-20261005`＝C1 的第 35、40、55、64 條（同一份原件、不同定位）、`tpex-rules-current-selaw-20261005`＝B2a、`tpex-rules-art55-selaw-20210111`＝B2b、`tpex-mainboard-system-intro`＝B1、`moj-securities-otc-trading-measures`＝B5c、`mof-securities-transaction-tax-act`＝B4、`moj-securities-transaction-tax-act`＝B6、`mof-tax-example-20260310`＝B7。

### 50.2 規則值與原文定位

| 元件 | 值 | 原文定位與必要短引文 |
| --- | --- | --- |
| tick | 股價 <10：0.01；10 ≤ 股價 <50：0.05；50 ≤ 股價 <100：0.1；100 ≤ 股價 <500：0.5；500 ≤ 股價 <1,000：1；≥1,000：5 | 業務規則第 55 條第 2 項：「…每股市價未滿十元者為一分，十元至未滿五十元者為五分，五十元至未滿一百元者為一角，一百元至未滿五百元者為五角，五百元至未滿一千元者為一元，一千元以上者為五元」。第 2 項在 B2b（110-01-11 版）與 C1（115-10-05 版）逐字相同；B1 官網表同值。每級下界含、上界不含，依「至未滿」措辭。 |
| 交易時間 | 09:00～13:30 | 業務規則第 40 條第 1 項前段：「櫃檯買賣之交易時間，除另有規定外，其交易時間如下」，第 1 款：「股票採等價成交系統者為上午九時至下午一時三十分；…」。B1：「撮合成交時間為9:00至13:30」。 |
| 申報輸入起點 | 08:30（開市前 30 分鐘） | 第 35 條第 1 項：「等價成交系統之買賣申報，得自市場交易時間開始前之三十分鐘起輸入」；B1：「委託時間8:30至13:30」。 |
| 暫緩開市、收市 | 開市暫緩延緩 2 分鐘（09:02）；收市暫緩 13:31～13:33 續收申報、13:33 撮合 | 第 35 條第 4 項：「延緩二分鐘後依序撮合成交」「俟一時三十三分依序撮合成交」；僅適用符合暫緩標準者，例外：當日開始交易基準價低於一元之有價證券、認購(售)權證及分離後認股權憑證。 |
| 收盤集合交易起點 | 13:25 | **只見於 B1**：「13:25至收巿（即13:30收盤）採集合交易」。第 35 條第 2、3、5 項只稱「收市前一段時間」，長度由本中心另訂標準公告，規則文字不含 13:25。 |
| 交易日 | 星期一至星期五 | 只見於 B1：「櫃檯買賣巿場交易時間為星期一至星期五」。第 41 條：「櫃檯買賣之休假日與銀行休假日相同。但本中心認為有變更之必要時，得報請主管機關核定後實施」；日曆由 #13 (b) 承接，本模組不判定休市。 |
| 賣方證交稅 | 0.003，非當沖普通股 | 證券交易稅條例第 2 條第 1 款：「公司發行之股票及表明股票權利之證書或憑證徵千分之三」，向出賣人按每次交易成交價格課徵；第 3 條由代徵人於交割當日代徵。第 2-2 條現股當日沖銷 1.5‰（106-04-28～116-12-31）不在本版，`day_trade=True` 拒絕。B7 算例 200,000 股×90 元×3‰＝54,000 元，僅示範成交價格×股數×3‰；算例情境為已簽證發行股票之未上市公司股東出售（代徵人為買受人），非上櫃普通股集中交易。 |
| 稅額元以下處理 | 來源未定 | B4、B6 全文與 B7 算例皆無尾數規定，來源未定。 |
| 手續費 | 無統一費率、上限或最低金額；千分之一點四二五是「逾者須事前通知客戶」的門檻 | 第 64 條第 3 項：經紀商「得按客戶成交金額自行訂定費率標準，另得訂定折讓及每筆委託最低費用，並於實施前…申報本中心備查」，「…所訂手續費率逾成交金額千分之一點四二五者，應於實施前以適當方式通知客戶，並留存紀錄。但客戶為境外華僑及外國人者，得於給付結算前通知」。第 2 項費率由本中心擬定報主管機關核定；管理辦法（B5c）第 14 條只定核定程序，第 7 條第 4、6 款為業務規則應訂營業時間與升降單位的授權依據。手續費捨入方式來源未載。 |

### 50.3 讀用契約

- 每個讀用函式都要明示 `market`（只收 `TPEx`）、`security_type`（只收 `ordinary_share`）、`rule_version`、`on_date`；其他值或未知版本拒絕，不推論 TWSE、興櫃或 latest。
- 來源未載生效日的元件（tick、交易時段、證交稅、手續費門檻；證交稅條例與管理辦法的頁面只載修正日期，selaw 全文頁只載版本發佈日），預設擲 `PendingEvidenceError`（`<元件>:effective_date_unverified`）；caller 以 `accept_published_only=True` 明示 opt-in 才取得值，輸出標 `effective_date_unverified` 與 `published_on`。
- 日期窗以各元件閘門來源的版本日為下界：tick 2021-01-11（第 55 條第 2 項在 2021-01-11 與 2026-10-05 兩版相同，中間版本未讀）；交易時段與手續費 2026-10-05；證交稅 2025-01-02（條例頁首修正日期，只作下界，不是生效日）。早於版本日、晚於擷取日 2026-10-12（`after_verified_date`）一律拒絕，opt-in 不放行。
- 時間邊界：來源以「A 至 B」描述且未載端點是否含入，恰在 08:30、09:00、13:25、13:30 回報 `boundary`（`unspecified_by_source`），不指派所屬時段。
- 證交稅回傳 `tax_exact`（未捨入）；`rounding`（floor／half_up／ceil）是 caller 宣告，輸出標 `caller_declared:*`，`official_rounding_status` 恆為 `pending_evidence`。
- 手續費由 caller 以 `CallerFeeTerms`（rate、discount、整數元 minimum、rounding）具名提供，輸出標 `caller_declared`；費率逾 0.001425 只標 `above_notification_threshold`，不拒絕。

### 50.4 授權與讀取額度

方案與核准保存在 [#97](https://github.com/YiCheng0608/stock-lab/issues/97)。公開規則文件，不登入、不付費，不需 seal。已讀未採用：證券商管理規則第 40 條（保管，與手續費無關）。

### 50.5 限制

- selaw 為彙編來源；逐條生效日、發布機關公告原件與金管會核定函未讀。
- 2021-01-11 與 2026-10-05 之間的業務規則版本未讀；第 55 條第 4 項（初次上櫃升降幅度）兩版不同，本節不採用該項。
- 13:25 收盤集合交易起點與星期一至星期五只有官網說明；各時間邊界的端點語意、手續費捨入、證交稅尾數處理，來源未載。
- 基本時刻表（`session_phase`）不涵蓋兩項例外，不判定個股是否適用：管理股票分盤交易（C1 第 35-3 條第 2 項：「櫃檯買賣管理股票應採分盤方式交易，每四十五分鐘撮合一次」）；盤中瞬間價格穩定機制（B1「一、交易時間」：「開盤後有價證券之任一試算成交價超過參考價格之3.5%（包含上漲及下跌），將延緩逐筆交易撮合2分鐘，並於2分鐘後以集合交易撮合」）。
- 不處理：交易日曆與休市、停復牌、公司行動、漲跌幅、零股、盤後定價、鉅額、價格觸及與成交、TWSE 及興櫃；不證任何單一股票屬 TPEx 普通股。
- 上表 SHA-256 識別擷取當時的 bytes；官網頁面會更新，重讀可能不同，差異須如實記錄，不冒同一 snapshot。

## 51. #33：TAIEX 名目指數兩截止 21 觀測 return（issue33-taiex-nominal-observation-cutoffs-1005-1006-v1）

2026-10-12。#33 以 FinMind 公開 API v4 `TaiwanStockPrice`（`data_id=TAIEX`）取得 2026-09-03～2026-10-06 的 provider-reported 名目指數日線，供 2026-10-05、2026-10-06 兩個截止日各取「截止日（含）向前 21 個觀測日」的 `get_taiex_nominal21` getter，以及 `taiex-nominal-price-index-window-summary-v1` snapshot consumer（20 個間隔的名目指數 return，精確有理數）。產品 `backend/app/taiex_price_index_source.py`，測試 `backend/tests/test_taiex_price_index_source.py`。本節只管理這個新 namespace，不提升也不改寫其他節的 policy、pins、capture 或 default；觀測日集合由 [§31.2](#312-24日完整觀測日曆與20日金融集合)的已驗交易日導出，不由 FinMind 回傳推導。取得過程與 QA 收據保存在 [#33](https://github.com/YiCheng0608/stock-lab/issues/33)；共同規則見 [FinMind 來源共同規則](#finmind-來源共同規則)。

本單有兩個來源方案：AC 修訂 1 為 TWSE `MI_5MINS_HIST` 政府 CSV 加 FinMind 的兩來源（namespace qa1）；AC 修訂 2 依使用者決策只用 FinMind，取代修訂 1 的對應項（namespace qa2）。產品與本節契約只對應 AC 修訂 2，不含任何政府 CSV 路徑。本節不含任何取回的價格列、原始 body 或 close 值（它們只在 RAM，已隨 release 清除），只記錄兩個 return 的最簡分數（見 [§51.3](#513-原件驗證與窗口consumer-計算)）。

### 51.1 版本、外部 pins 與上限

| 項目 | 內容 |
| --- | --- |
| 外部 policy | version `issue33-taiex-nominal-observed-window-finmind-v2`，schema `issue33-taiex-nominal-observed-window-policy/v2`；canonical 5,038 UTF-8 bytes（sorted keys、compact JSON、無尾 LF）；SHA-256 `04be101a61b6eba5ae6ba5773c24314718765c37ae7c67eacfd8813efb64d9dc`，由全局發布。產品只接受 v2 與 namespace `issue33-taiex-nominal-observation-cutoffs-1005-1006-v1/qa2`；qa1 時期的 policy（4,096 B，SHA-256 `4b1f44b0e77950bcd12896f5e54f99c6262365fcf4965b4938420edb58e54eca`）與 qa1 namespace 的值都被拒絕 |
| profile／用途 | profile `free_public_local`；source_use `local_personal_noncommercial_process_ram_nominal_observation_snapshot`；market TW/TWSE、instrument_type `price_index`、symbol `TAIEX`、identity_as_of 2026-10-06；storage `process_RAM`；consumer `taiex-nominal-price-index-window-summary-v1`；輸出 `price_basis` 為 `nominal_index_level`、`calendar_basis` 為 `cross_market_candidate_inference` |
| 來源 | FinMind，dataset `TaiwanStockPrice`，`data_id=TAIEX`；欄位 open→`open`、high→`max`、low→`min`、close→`close`；已知不採用欄 `Trading_Volume`、`Trading_money`、`Trading_turnover`、`spread` |
| 日期與截止 | 請求區間 2026-09-03～2026-10-06；cutoff 2026-10-05、2026-10-06 |
| 請求 | 固定 1 個 GET，host 只有 `api.finmindtrade.com`：`https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice&data_id=TAIEX&start_date=2026-09-03&end_date=2026-10-06`（query 依序 dataset、data_id、start_date、end_date）。不換 dataset、`data_id`（如 `^TWII`）、日期、路由或 namespace 再試 |
| 請求標頭 | 明設四個：`Accept-Encoding: identity`、`Connection: close`、`User-Agent: stock-lab-issue33-local-ram/1`、`Accept: application/json`；另有 `http.client` 依 URL 自動加的 `Host`；不帶 token、cookie、proxy |
| 上限 | body 1 MiB（1,048,576 B）、aggregate raw 1 MiB、retained-roots estimate 32 MiB（33,554,432 B）；該 URL 20 s、整批 180 s；`max_gets` 1、`artifact_bytes` 0；其餘同共同規則 |
| 固定 formal 參照 | 觀測日集合由固定 blob `d8918bc6491ec8ef65874979cf88d1322df2da43:docs/SOURCE_REGISTRY.md`（268,729 B；SHA-256 `b5ea9605c75add4bfa5581672d3778ac2851a29ac599e3e0b9e938880f42abde`）的 §31.2 解析。呼叫者必須提供該 blob，位元組、長度或 SHA-256 不符即 `formal_blob_pin` 拒絕，發生在 GET 之前，不花用額度。這個 pin 指向 commit 內容，不隨本檔後續編修而變 |

### 51.2 用途、授權與署名

用途只限免費公開、本地個人非商用研究與 RAM 取得／驗證／consumer。Policy 的 `unsupported` 共 19 項：`historical_pit`、`publication_time`、`first_availability`、`revision_history`、`verified_twse_calendar`、`canonical_20_trading_day_benchmark`、`adjusted_basis`、`total_return`、`independent_unit_anchor`、`hot_group_v1`、`canonical_regime`、`actionable_strategy`、`plan`、`trading`、`historical_simulation`、`raw_disk_storage`、`redistribution`、`mirror`、`other_cutoffs`。不落盤、不發布 raw、不鏡像。權利字串（policy `rights`，逐字，與 [§49.2](#492-用途授權與署名)相同）：`FinMind personal noncommercial local RAM; attribution; no raw redistribution or mirror`，隨 policy SHA-256 被 seal 綁定。Policy 沒有固定完整署名文字；產品 provenance 的來源欄載明 `FinMind TaiwanStockPrice data_id=TAIEX (personal noncommercial; attribution; no mirror/raw redistribution)`，並帶出 `rights` 與 `data_id_evidence`（署名方式見 [FinMind 來源共同規則](#finmind-來源共同規則)）。

免費使用與 `data_id=TAIEX` 都是推論，不是 FinMind 的明示陳述。免費使用的依據同 [§49.2](#492-用途授權與署名)（policy 引用 `https://finmind.github.io/tutor/TaiwanMarket/Technical/`），Policy 因此規定 401、402、403 或任何要求付費、登入的回應是首敗。`data_id=TAIEX` 的證據是 maintainer legacy 名稱與目前 daily v4 路由的推論，實際是否被接受只由唯一一次 GET 證明。使用者已接受三項已知風險：`data_id=TAIEX` 推論、免 token 推論、點數尺度無第二來源；跨來源互核改為 FinMind 內部一致性並列限制，Issue #53 不綁本單，維持 RAM-only。

### 51.3 原件驗證與窗口／consumer 計算

- **傳輸**：逐項沿用 [§49.3](#493-原件驗證與-last60summary-計算)的「取得」與「標頭」兩點：只收 HTTP 200；`content-encoding` 須 identity 或無；`content-type` 為 `application/json`（可接 `; charset=utf-8`）；framing 接受 content-length、chunked、close-delimited，content-length 與 chunked 並存拒，達上限仍無 EOF 拒；四個身分標頭（`content-length`、`content-encoding`、`transfer-encoding`、`content-type`）重複即拒，其他標頭重複忽略，`set-cookie` 不送出、不使用、不保存；完整 EOF 與 raw hash 通過後才 parse，strict UTF-8、無 BOM。與 [§49](#49-32-qa1qa2七股-finmind-nominal-ohlcv-日線-last60-與兩截止-raw-算術issue32-seven-nominal-ohlcv-two-cutoffs-v1) 的差異如下表。
- **JSON 與 document**：重複鍵、nonfinite（`NaN`、`Infinity`）與 bool 當數值一律拒；回應須為 `{status:200, msg:"success", data:[…]}`，`data` 為 1～20,000 列。數值受有界工作限制：整數字面至多 64 字元且絕對值至多 10^18；小數字面至多 64 字元、有效位數至多 64、指數與 adjusted exponent 的絕對值至多 18。這些界線比 AC 嚴格，也適用於不採用欄與區間外列；真實指數點數不會觸及。
- **列結構（全部回傳列）**：每列須有 `date`、`stock_id`、`open`、`max`、`min`、`close`；四個已知不採用欄（`Trading_Volume`、`Trading_money`、`spread`、`Trading_turnover`）可缺，有則接受 JSON number、string、null，bool、list、object 拒（`finmind_unadopted_type`），不驗範圍與正負，不進任何計算或輸出；其他未知鍵拒。`stock_id` 恰為 `TAIEX`；`date` 為合法 ISO 日期、唯一且遞增。採用欄 `open`、`max`、`min`、`close` 須為 JSON number，否則 `finmind_numeric_type`。全部回傳列先驗上述結構，之後才捨棄 2026-09-03～2026-10-06 以外的列，所以來源是否依 `start_date`／`end_date` 過濾都不影響結果；區間內須恰 22 列。
- **內部一致性（取代官方 anchor）**：區間內 22 個日期須與固定 22 日集合完全相同：[§31.2](#312-24日完整觀測日曆與20日金融集合)的 Sep20 自 2026-09-03 起 18 日（9/3、4、7、8、9、10、11、14、15、16、17、18、21、22、23、24、29、30）加 Oct4 的 4 日（10/1、2、5、6）；9/25、9/28 為 §31.2 公告的閉日，不在集合內。不從缺列推休市、不縮窗、不採區間外日期。區間內每列 OHLC 須為有限正 Decimal，且 `min ≤ min(open, close) ≤ max(open, close) ≤ max`；違反任一列整批拒，不補值、不挑列。
- **完整 oracle**：產品解析結果須與獨立 oracle 對**全部回傳列、全部欄位**逐值 typed-equal 才 available：日期與 `stock_id` 為字串，採用欄為 Decimal，不採用欄原樣（number 為 Decimal，string 與 null 不轉型）。oracle 缺欄、換型別、重排、少列、或事後改動 raw 皆拒。取得完成後狀態為 pending，通過 oracle 才原子轉 available；failed、expired（租約至多 180 s，且不晚於 seal 到期）與 released 都拒用。
- **單位**：名目指數點數，scale 1，不乘除 1000；`provider_literal_unit_annotation` 為 false，`independent_unit_anchor` 為 false，policy `unit_mapping_inference` 為 true（version `issue33-finmind-only-scale1-v2`）。TWSE `MI_5MINS_HIST` 的獨立點數 anchor 已依使用者決策移除，consumer 與 oracle 的比對只是同一份 bytes 的內部一致性，不是獨立尺度驗證。
- **窗口與 getter**：窗口含 cutoff，取截止日（含）以前最後 21 個觀測日，不縮窗：2026-10-05 為 2026-09-03～2026-10-05，2026-10-06 為 2026-09-04～2026-10-06。`get_taiex_nominal21(cutoff)` 回傳可撤銷 handle，內容為 cutoff、21 筆（date、close）、`first_date`、`last_date`、`observation_count` 21、`interval_count` 20、`calendar_basis` `cross_market_candidate_inference`、`price_basis` `nominal_index_level`、`benchmark20d_ready` false、provenance。
- **summary**：`summarize(cutoff)` 的 consumer 為 `taiex-nominal-price-index-window-summary-v1`，`return` R 為 `(C_end − C_start) / C_start`，C_start 為窗口第一日 close、C_end 為最後一日 close，表示為最簡整數分子與正分母，不用浮點、不做 context 捨入；`observation_count` 21、`interval_count` 20。
- **provenance**：只列 FinMind；帶出 policy pin／SHA-256／version、seal pin／SHA-256、namespace、formal 日曆 blob、`rights`、`data_id_evidence`、單位欄位與限制、policy `unsupported`、capture receipts 與 execution binding；`publication_time`、`first_availability`、`revision_time` 固定 `unknown`，`verified_twse_calendar`、`adjusted_basis`、`total_return` 固定 false。
- **拒用**：cutoff 不是兩個截止日回 `unsupported_cutoff`；用途或 consumer 不是固定值回 `unsupported_getter_use`、`unsupported_consumer_use`；failed、expired 與 released 的 getter、summary 皆拒；release 後既有 handle 的 visit 與 declared roots 讀取回 `lease_released`。
- **pre-GET 拒用**：external policy（SHA-256、bytes、canonical 序列化與型別）、financial-start seal（24 欄、獨立 QA 與 owner 身分、候選與程式 hash、namespace、唯一 URL、用途、consumer、cutoff、caps、有效期，且 pin 須為 #33 內 AC 修訂 2 之後的留言）、formal blob pin 與 execution binding 任一不符，皆在 GET 之前拒絕，不花用額度。Policy 內的 `policy_pin` 只驗 URL 形狀（任一 issue 留言皆可），權威是 policy 的 SHA-256 與 bytes。

qa2 唯一一次取得的兩個 return（最簡分數，與獨立 `Fraction`、整數 gcd 兩套算法相等；區間內 22 個日期與固定 22 日集合完全相同，`data_id=TAIEX` 在該次 GET 被接受）：

| cutoff | 窗口（21 觀測日） | R |
| --- | --- | --- |
| 2026-10-05 | 2026-09-03～2026-10-05 | 192719/2292883 |
| 2026-10-06 | 2026-09-04～2026-10-06 | 327142/4655113 |

與 §49 的傳輸差異：

| 項目 | #32（§49） | 本單 |
| --- | --- | --- |
| GET 數與來源 | 8（交易日 1、價格 7） | 1（價格 1），policy 沒有 per-source 上限 |
| aggregate raw | 8 MiB | 1 MiB（body 上限同為 1 MiB） |
| `User-Agent` | `stock-lab-issue32-local-ram/1` | `stock-lab-issue33-local-ram/1` |
| `artifact_bytes` | 未列 | 0，明列 |
| document 規則 | 交易日與價格各有列規則 | 單一 `data` 列規則：必要鍵、已知不採用欄的型別、`stock_id` 恰為 `TAIEX`、區間內恰 22 列 |
| 零價列 | OHLC 為 0 的列整批拒 | 只針對區間內列整批拒；區間外列只驗結構（採用欄仍須為 JSON number）後捨棄 |
| HTTP 狀態 | 非 200 皆 `http_status` | 401、402、403 為 `http_auth_or_payment_stop`，其他非 200 為 `http_status_stop`；兩者皆首敗 |
| `Content-Length` 文法 | 十進位文字不限位數 | 十進位文字至多 16 位，其餘規則相同；數值仍受 body 與 aggregate raw 上限約束 |

### 51.4 qa2：成功取得與驗證結果

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/SOURCE_REGISTRY.md` §51.4（原「#33 qa2：成功取得與驗證結果」）。

### 51.5 qa1：SPENT

歷史收據：`git show 767b57733074627cde15c858a5aa7a2a6f68f927:docs/SOURCE_REGISTRY.md` §51.5（原「#33 qa1：SPENT」）。

### 51.6 未驗與限制

- **點數尺度沒有獨立錨點**：單位與 scale 1 是推論；所有 consumer／oracle 比對都只是同一份 bytes 的內部一致性，不證 adjusted、index-divisor 歷史、total-return 或完整 TWSE calendar。
- **日曆**：22 日相等只證 FinMind 在請求區間內的觀測集合等於 §31.2 的集合，不證完整 TWSE 交易日，也不證 9/25、9/28 休市；§31.2 的日曆來自 TPEx 來源，不是已驗的 TWSE 日曆，因此 `calendar_basis` 固定為 `cross_market_candidate_inference`，`verified_twse_calendar` 為 false。
- **`data_id=TAIEX` 與指數口徑**：qa2 的單次成功只證那次 GET 回傳 `stock_id` 為 `TAIEX` 的 22 列；FinMind 對此 id 的長期可用性與指數口徑（provider-reported）沒有承諾。
- **非 PIT**：publication、first availability、revision 皆 `unknown`；不證穩定、限流或條款日後不變。
- **qa2 輸出沒有記錄**：回傳總列數（body 4,542 B 約合 22 列，是推論）、回應標頭名稱與 framing 形式、不採用欄的實際值型別；真實回應的這些細節未知，由產品的邊界測試涵蓋。
- **有界工作與列界線嚴格於 AC**：整數、小數的字面與指數上限（見上）適用於區間外列與不採用欄；區間外列的採用欄也須為 JSON number，否則整批拒；回傳列過多時 retained estimate 逼近 32 MiB 會 fail-closed（約 5,000 列以上）；exact-cap 的 chunked 或 close-delimited 回應因 EOF 未知而拒。實際回應約 22 列，不受影響。
- **不支援**：Policy 的 `unsupported` 19 項（見上）；其他 cutoff、dataset、`data_id`、日期與用途在取數前拒用，不外推。價格列只在 RAM，已釋放；要再取需新的明示使用者授權、新 namespace 與新 seal，NO-RETRY 照舊，不 restart、replay、clone 或 hydrate 已釋放的資料。
- **已接受風險**：免費使用是文件推論，qa2 的 HTTP 200 只代表當時；gzip、br 回應被拒，區間內 OHLC 非正的列整批拒收（policy 列為已接受風險），qa2 皆未觸發。
- **未在真實來源驗到**：failed 與 expired 後拒用、launcher trace 的 first coded origin、租約 expiry 在真實 run 沒有觸發，只有網路 0 階段的邊界測試與演練；chunked、close-delimited、charset 變體、非身分標頭重複與 `set-cookie` 只有 RAM 重放證據；401、402、403 與零價列的真實路徑未觸發。
- **防護性質**：閘門、audit hook 與 trace 是進程內協作式防護，不是沙箱；retained estimate 不是 RSS 或 peak，生命週期驗收不代表實體抹除。
- **版本與依賴**：本節描述 candidate `b5072b08…` 的契約與 qa2 結果；其後程式、policy 或驗收語意變動須重驗並更新本節。本節不宣稱解除母單 #21 的整體 AC 或 V1 的依賴。

## #9 qa1：七股 FinMind 自行買賣與避險五日淨額原件（issue9-dealer-direction-combos-finmind-v2）

#9 以 FinMind `TaiwanStockInstitutionalInvestorsBuySell` 取得七股 2026-09-29～2026-10-06 的法人買賣原列，供截止日 2026-10-06 的自行買賣（`Dealer_self`）與避險（`Dealer_Hedging`）五日方向組合 consumer（產品 `backend/app/finmind_dealer_direction_source.py`、`backend/app/institutional_dealer_direction_combos_scope7.py`，測試 `backend/tests/test_finmind_dealer_direction_source.py`、`backend/tests/test_institutional_dealer_direction_combos_scope7.py`）。本節只管理這個新 namespace，不提升也不改寫其他節的 policy、pins、capture 或 default；日曆用 [§31.2](#312-24日完整觀測日曆與20日金融集合) 的固定交易日，不取日曆（calendar GET 0）。頁面操作見[個股頁](STOCK_RESEARCH_PAGE.md#9七股自行買賣與避險五日方向組合頁)，驗證入口見[開發入口](development-baseline/README.md#9-七股自行買賣與避險方向組合的零落盤驗證入口)。取得過程與 QA 收據保存在 [#9](https://github.com/YiCheng0608/stock-lab/issues/9)，下列為摘要並附留言編號。本節不含任何取回的列、原始 body 或衍生數值；它們只在取得進程的 RAM，進程結束即釋放。

### #9 版本、外部 pins 與上限

| 項目 | 內容 |
| --- | --- |
| 外部 policy | version `issue9-dealer-direction-combos-finmind-v2`；canonical 9,319 UTF-8 bytes（sorted keys、compact JSON、`ensure_ascii`、無尾 LF）；SHA-256 `7db5e7a7e17f883e7e4e81de297ce2e4ad8c6c4fcde409b7cbeae0eaa56696b1`。由全局發布於 [#9 留言 6128262506](https://github.com/YiCheng0608/stock-lab/issues/9#issuecomment-6128262506)，內容採 [留言 6125240011](https://github.com/YiCheng0608/stock-lab/issues/9#issuecomment-6125240011) 的 v2 草案原文，不改任何位元組；產品不能由被測 policy 自建 expected，canonical bytes、SHA-256 與位元組長度須由呼叫端另帶 |
| source／consumer | provider FinMind，dataset `TaiwanStockInstitutionalInvestorsBuySell`；source_use `local_personal_noncommercial_dealer_self_hedging_direction_combos`；profile `free_public_local`；市場 TW/TPEx、普通股、截止日 2026-10-06；consumer `dealer-self-hedging-direction-combos-five-session-v1` |
| namespace | `issue9-dealer-direction-combos-finmind-v1/qa1`（字串中的 `v1` 是 namespace 名稱，不是 policy 版本） |
| 標的與日期 | TPEx 3105 穩懋／3293 鈊象／5274 信驊／5347 世界／6488 環球晶／6510 精測／8069 元太；請求範圍 2026-09-29～2026-10-06；固定交易日為 §31.2 的 2026-09-29、09-30、10-01、10-02、10-05、10-06（09-25、09-28 為閉日）；窗口五日為 09-30～10-06，09-29 只用作 anchor，不進方向計算 |
| 請求 | 固定 7 個 GET，不取日曆：`https://api.finmindtrade.com/api/v4/data`，query 依序 `dataset=TaiwanStockInstitutionalInvestorsBuySell`、`data_id=<代號>`、`start_date=2026-09-29`、`end_date=2026-10-06`，依 3105、3293、5274、5347、6488、6510、8069 升序；不換 provider、日期或路由 |
| 請求標頭 | 明設四個：`Accept-Encoding: identity`、`Connection: close`、`User-Agent: stock-lab-issue9-local-ram/1`、`Accept: application/json`；另有 `http.client` 依 URL 自動加的 `Host`；不帶 token、cookie、proxy |
| 上限 | 每份 body 1 MiB（1,048,576 B）、aggregate raw 8 MiB（8,388,608 B）、retained-roots estimate 32 MiB（33,554,432 B；estimate 不是 RSS 或 peak）；每 URL 20 s、整批 180 s（cooperative）；redirect 0、retry 0、每 URL 最多 1 次；首敗即停且 attempted 即 SPENT；只在 RAM |
| 固定 formal 參照 | policy `anchors` 指向固定 blob `116bfab818fc5f72a650573c611d62b662372026:docs/SOURCE_REGISTRY.md`（234,262 B；SHA-256 `f27024ba1f4d5874610e3446cae34401dbeab4ea485706704e78cd4ef3844240`）的 §47.6 兩個截止日五日淨額表（現行文見 [§47.3](#473-原件驗證與五日分子計算)）。產品只核 policy 內的 anchor 值；blob 位元組與該表由獨立 oracle 核對。這個 pin 指向 commit 內容，不隨本檔後續編修而變 |

### #9 用途、授權與署名

用途只限免費公開、個人非商用、本地盤後研究與 RAM 取得／驗證／consumer。產品的 `purpose` 只接受上列 source_use，其餘一律 `unsupported_purpose`；呼叫端帶任何 `lease_seconds` 回 `lease_policy_conflict`（originals 持有到進程結束，沒有時鐘租約）。Policy `unsupported`（逐字）：`historical_pit`、`publication_time`、`first_availability`、`revision_guarantee`、`other_dates`、`other_symbols`、`other_cutoffs`、`ranking`、`filtering`、`price`、`signal`、`plan`、`trading`、`actionable_strategy`、`raw_disk_storage`、`cross_process`、`db`、`redistribution`、`mirror`、`deployment`、`official_unit_annotation`。

權利字串（policy `source.rights`，逐字）：`FinMind personal noncommercial local RAM; attribution; no raw redistribution or mirror`。Policy 沒有固定完整署名文字，也沒有引用 FinMind 條款全文或條款版本；FinMind 是服務提供者，不是官方直接來源。權利是否充分是使用者決策：沿用 FinMind 為主的決策（[#1 留言 6115274136](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-6115274136)）與來源選用原則，並在 [#1 留言 6124017937](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-6124017937) 確認不另問；QA 只核對它被 seal 綁定。

免費使用是文件推論，不是明示陳述。FinMind 文件 `https://finmind.github.io/tutor/TaiwanMarket/Chip/`（`finmind.github.io` 2 GET，`api.finmindtrade.com` 0 次，body 718,372 B，SHA-256 `cfcf26a8269452d0a2c396ca69a5a371bcba68d55b2ab35d432b1ba1de13b5f3`，[留言 6124059360](https://github.com/YiCheng0608/stock-lab/issues/9#issuecomment-6124059360)）顯示：

- 帶 `data_id` 的個股查詢沒有 backer／sponsor 標記，只有不帶 `data_id` 的全市場日查詢標示只限 backer、sponsor 會員；本方案逐股帶 `data_id`。範例帶空字串 token，「可免 token」仍是推論，因此 401、402、403 或任何要求付費、登入的回應是首敗。
- 回應列的 schema 是 `date`、`stock_id`、`buy`、`name`、`sell` 五欄，沒有淨額欄、沒有 `Note`；文件沒有任何單位字樣。
- 數值可能於初次公布後微幅更新：盤後定價、鉅額配對等可能事後補計進當日，若買賣屬同一法人別，買進與賣出會等額增加、淨額不受影響；官方沒有固定的定案時間。因此取得值一律標「API 當下值」（非 PIT）。

`name` 全部列舉（文件表格）與本 policy 的處置，比對為精確字串（大小寫與空白皆須相同）：

| name | 文件說明 | 本 policy |
| --- | --- | --- |
| `Foreign_Investor` | 外資（不含外資自營商） | 收；在 anchor 內 |
| `Foreign_Dealer_Self` | 外資自營商 | 收；只作五個 name 完整性核對，不在 anchor 內 |
| `Investment_Trust` | 投信 | 收；在 anchor 內 |
| `Dealer_self` | 自營商（自行買賣） | 收；在 anchor 內 |
| `Dealer_Hedging` | 自營商（避險） | 收；在 anchor 內 |
| `Dealer` | 自營商（合併），文件稱約 2014-12-01 前與興櫃使用 | 出現即整批拒用 |

qa1 是一次額度，授權本身不是 seal；real run 另須全局核發 fresh financial-start seal，並由獨立 QA 執行一次。

| 項目 | qa1 |
| --- | --- |
| namespace | `issue9-dealer-direction-combos-finmind-v1/qa1` |
| 取得方案與授權 | 使用者決策 [#1 留言 6124017937](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-6124017937)（AC 修訂 2：改取 FinMind、RAM-only 單次生命週期），全局處置 [#9 留言 6124018483](https://github.com/YiCheng0608/stock-lab/issues/9#issuecomment-6124018483)；零值形狀改為只記錄比對（AC 修訂 2a）：[留言 6124127920](https://github.com/YiCheng0608/stock-lab/issues/9#issuecomment-6124127920) |
| seal | 全局 [#9 留言 6134552574](https://github.com/YiCheng0608/stock-lab/issues/9#issuecomment-6134552574)；使用者核准 [#1 留言 6134500330](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-6134500330)（#9 與 #39 各自取得，不共用） |
| candidate | `9726546eb6a8a13ed09b1ee7b5843d816894fd05` |
| 載入的來源檔 SHA-256 | `8479a07070cfc1a1eb7f4de141711c343f00bbfe259ef83a95fba4d2a5c53308`（`backend/app/finmind_dealer_direction_source.py`；其後的 `234b9a22cf577640ecac776be9c6f5ca8b0fb7dc` 只改前端返回連結與 preview 檢查，此檔位元組不變） |
| QA oracle／admission 腳本 SHA-256 | `4cfea6cd64000caa1cd170c969ec943584806a770408628bb3aabbd240860eab` |
| QA 結果 | [#9 留言 6134948764](https://github.com/YiCheng0608/stock-lab/issues/9#issuecomment-6134948764) |

產品對 seal 只做形狀與關係檢查：`FinancialStart` 的 version 為 `issue9-financial-start-v1`，namespace 與 policy SHA-256 相符，`authorized`、`whole_batch` 為布林 `true`；issuer、coordinator、implementer、QA holder 的 session id 為小寫 UUID 且彼此相異，holder 的 reasoning effort 為 `xhigh`；`candidate_sha` 為 40 位十六進位，`loaded_source_sha256`、`script_sha256` 為 64 位十六進位；`seal_comment_url` 指向 #9 留言且編號大於 6124225468。產品不認證 GitHub 或 runtime 身分，`loaded_source_sha256`、`candidate_sha` 與 `native_command` 也不與實際載入的檔案或命令列比對，所以服務身分（PID、啟動時間、命令、來源 worktree、埠、bundle 雜湊）須由獨立 QA 另行讀回。

### #9 原件驗證、gate 與方向組合計算

傳輸規則比照 [§48.3](#483-原件驗證與五日變動比計算)、[§49.3](#493-原件驗證與-last60summary-計算)，下列為本節實際行為：

- **取得**：只接受 HTTP 200（其他狀態含 3xx 一律拒用；有 `location` 即 `http_redirect`）。`content-encoding` 缺少或為 `identity`（不分大小寫），gzip、br 拒。`content-type` 為 `application/json`（不分大小寫），可接 `; charset=utf-8` 或 `; charset="utf-8"`，其他參數與媒體型別拒，長度上限 128 字元。Framing 接受 `content-length`、chunked、close-delimited（讀到 EOF，受 1 MiB 限制）：`transfer-encoding` 只接受 `chunked`；`content-length` 須為無前導零的十進位，超過 body 上限或與實際讀到的長度不符即拒，並存 chunked 即拒；達上限仍無 EOF 拒；空 body 拒。`content-length`、`content-encoding`、`transfer-encoding`、`content-type`、`location` 任一重複即 fail-closed，其他標頭重複（如 `cache-control`、`vary`、`set-cookie`）接受並忽略；不送出、不使用、不保存 cookie。完整 EOF 與 raw hash 通過後才 parse。以 stdlib 直接建立連線；`http.client.HTTPSConnection` 被替換時以 `transport_class_replaced` 在花用額度前拒用，稽核須以 `connection_factory` 組合包裝。
- **JSON 與 envelope**：strict UTF-8、無 BOM（`bom_rejected`）；重複 JSON 鍵、任何浮點字面值、NaN、Infinity 一律拒用；envelope 恰為 `msg`、`status`、`data` 三鍵，`status` 為整數 200、`msg` 為 `"success"`，`data` 為 1～10,000 列。
- **列結構**：每列恰為 `buy`、`date`、`name`、`sell`、`stock_id` 五鍵（缺鍵、多鍵都拒）；`date` 為存在的 ISO `YYYY-MM-DD`；`stock_id` 等於請求代號；`name` 為字串；`buy`、`sell` 為 0 至 int64 上限的非 bool 整數。
- **先驗全部、再取範圍**：所有回傳列先驗結構，之後才捨棄 `start_date`..`end_date` 以外的列（範圍外列只驗結構，其 `name` 不必是上表五個之一），所以 FinMind 是否依範圍過濾都不影響結果。範圍內的列：`name` 只收上表五個，`Dealer` 或其他值整批拒用；同一 symbol-date-name 不得重複；日期集合須恰等於六個固定交易日，不從缺列推休市；每個日期須五個 name 各一列，缺列不當零。任一不符整批拒用，不跳過壞股、不補 0、不縮窗。
- **淨額與單位**：淨額＝`buy − sell`，在本地衍生（FinMind 沒有淨額欄），每一步以 signed int64 為界（溢位回 `arithmetic_int64_overflow`）。單位「股」是明示推論（policy `provider_literal_unit_annotation` 為 `false`）：文件沒有單位字樣，單位只靠下列 56 個官方 exact anchor 驗成股；張＝股 ÷ 1000，精確換算、至多三位小數，不用浮點。
- **anchor gate**：固定 blob §47.6（現行文 [§47.3](#473-原件驗證與五日分子計算)）的五日淨額共 56 個值整批 exact 核對，通過後才進 `pending`。截止 2026-10-05 用 09-29～10-05，截止 2026-10-06 用 09-30～10-06；每檔每截止日 4 個值：`foreign_investor`（`Foreign_Investor` 淨額和）、`investment_trust`、`dealer_self_plus_hedging`（`Dealer_self` 與 `Dealer_Hedging` 淨額和）、`three_total`（前三者之和，不含 `Foreign_Dealer_Self`）。任一不符整批拒用（`anchor_mismatch`），診斷只含日期、代號與鍵，不含數值。
- **零值形狀（只記錄，不拒用）**：窗口五日、七檔、`Dealer_self` 與 `Dealer_Hedging` 的 buy、sell、net 共 210 個值，期望的零值集合是 [§46.5](#465-本次actual與未驗) 記載的 5274 `Dealer_self` sell 於 2026-10-05、10-06（官方 TPEx CSV 的 gross）。比對結果只列入收據與 `record_only_comparison`；不一致不判為來源錯誤、不拒用（AC 修訂 2a），因為 FinMind 文件說明 buy／sell 可能事後等額補計。
- **admission**：取得完成的狀態是 `pending`，不是可用。獨立 oracle（只用標準函式庫，不呼叫產品的解析或計算函式）以同一份 RAM 原件重算後送 `OracleAdmission`，須綁定 7 份 canonical receipt 的 SHA-256（依請求序）、`name_rows` 210（7 檔 × 6 日 × 5 name）、`stock_days` 42、`anchor_values` 56，以及與產品相同的 `record_only_matches`；real 路徑另綁定 QA holder、candidate 與 script SHA-256。通過才 `available`，consumer 與頁面才可讀；`window_records` 只回五個窗口日，anchor-only 日不外露。
- **receipt**：每個 GET 一份，欄位 `source_id`（`finmind_institutional_investors/<代號>`）、`source_version`（policy version）、`method`、`url`、`status`、`request_started_utc`、`observed_utc`、`body_bytes`、`body_sha256`、`full_eof`、`content_type`、`content_encoding`、`namespace`、`policy_sha256`。Canonical receipt 為 sorted keys、compact JSON，其 SHA-256 即 canonical receipt SHA-256。
- **consumer 計算**（只在 `available` 後，以五個窗口日在本地 RAM 計算）：每日自行買賣與避險淨額（買進 − 賣出）的方向為正（> 0）、負（< 0）或零（＝ 0）；兩個方向的 3 × 3 共九種每日組合；相反方向日為「自行買賣正／避險負」或「自行買賣負／避險正」；各 component 的正、負、零日數；最大連續區段為同方向的最大連續日，零自成一段並中斷正負連續區段，窗口內最新區段是最後一段；首段永遠標 `earlier_unknown`，不推窗口之前的延續。缺值或未知不當零，任何來源、pin、schema、name、日期、anchor 或算術衝突使七檔整批不可用。
- **追溯**：segment → date → 該股該日全部五個 `name` 原列（原值、`row_index`＝該列在回應 `data` 中的 0 起序號、`key_order`）加 body SHA-256、canonical receipt SHA-256、URL 與 §31.2 日曆參照。

### #9 生命週期與 SPENT 帳

- **狀態**：`new` → `acquiring` → `pending` →（獨立驗證准入）→ `available` → `released`；首敗為 `failed`；`expired` 只在生命週期擁有者呼叫 `release(expired=True)` 時進入。Policy `lease` 為 `held until process exit`：originals 持有到進程結束，沒有時鐘租約。`pending`、`failed`、`expired`、`released` 對 consumer 都是惰性。`release` 清空所有擁有的 roots，但一次性 ledger 保留、不重置。
- **RAM-only 單次**：取得進程內取得一次，撐完整個瀏覽器操作，進程結束即釋放；重來須新額度、新 namespace 與新 seal。一個 ledger 只容一批，attempted（含連線前就失敗）即 SPENT，同進程的新 source 物件一律 `quota_spent`。Ledger 是載入模組內的 RAM 計數，不是跨進程限流器，外部 seal 才是權威。
- **qa1 SPENT**：獨立 QA 於 2026-10-12（UTC）在 FIRST 可信點擊後送出 7 個 GET，全部成功（`attempted` 為 0～6、`request_count` 7），經獨立 oracle 准入後讀用；API 進程以 Ctrl+C 釋放（`state` 為 `released`）。**qa1 為 SPENT／NO-RETRY**：額度已用盡，不 restart、replay、clone、hydrate 或另開來源；原件與衍生 RAM 已釋放，不能離線重驗。再取需新的明示使用者授權、新 namespace 與新 seal（#9 與 #39 的取得各自獨立）。

### #9 未驗與限制

- **非 PIT，不證穩定**：發布時間、首次可得、修訂歷史與歷史 eligibility 未知（`unknown`）；取得值是「API 當下值」，之後 buy／sell 可能事後補計；一次成功不證匿名額度、限流或 FinMind 的長期穩定。
- **單位是推論**：「股」由 56 個官方 exact anchor 驗證，FinMind 本身沒有單位字樣；`Foreign_Dealer_Self` 不在 anchor 內。
- **JSON 整數字面值 `-0`** 會被解析成 0 而接受（policy 寫「非 bool 整數 0..max」）；實際 FinMind 不會送這種值。
- **逾時方向保守**：deadline 落在 charge 與 open 之間時，該 URL 會被記為 attempted（SPENT）但沒有建立連線，只會多記、不會少記。
- **防護性質**：閘門與 audit hook 是進程內協作式防護，不是沙箱；deadline 是 cooperative，不是 OS 硬 deadline；retained estimate 不是 RSS 或 peak，生命週期驗收不代表實體抹除。
- **零值形狀**：真實窗口的零值比對只記錄、不拒用；淨額為零、整窗為零等形狀沒有真實原件的紀錄，只有合成資料驗過。
- **範圍**：只對這七檔、截止 2026-10-06、這個 dataset 與本地 RAM 用途有效；其他日期、代號、市場、PIT、排名、篩選、價格、Signal、Plan、交易、DB、跨程序與落盤均不支援。
- **版本**：本節描述 candidate `9726546eb6a8a13ed09b1ee7b5843d816894fd05` 取得時的契約；其後程式、policy 或驗收語意變動須重驗並更新本節。

## #39 qa1：七股 FinMind 法人買賣與成交量及兩截止流向÷量比率（issue39-seven-flow-to-volume-ratio-two-cutoffs-v1）

2026-10-13。#39 以 FinMind 公開 API v4 取得七股 2026-09-01～2026-10-06 的法人買賣、日線成交量與交易日，供 2026-10-05、2026-10-06 兩個截止日的法人流向÷成交量 consumer（5 日三法人淨股數 ÷ 含截止日的 20 日均量；公式與門檻見 [V1_SPEC](V1_SPEC.md) 法人列）。產品 `backend/app/institutional_flow_ratio_source.py`（取得與准入）與 `backend/app/institutional_flow_ratio.py`（純計算 consumer），測試 `backend/tests/test_institutional_flow_ratio_source.py`、`backend/tests/test_institutional_flow_ratio.py`，QA 腳本 `tools/issue39_flow_volume_ratio_qa.py`。本節只管理這個新 namespace，不提升也不改寫其他節的 policy、pins、capture 或 default。取得過程與 QA 收據保存在 [#39](https://github.com/YiCheng0608/stock-lab/issues/39)，下列為本節特有的規則與邊界摘要並附留言編號，共同規則見 [FinMind 來源共同規則](#finmind-來源共同規則)；取回的列與原始 body 只在 RAM，已隨 release 清除；逐檔數值與 receipt 雜湊只記在 [#39 QA 收據](https://github.com/YiCheng0608/stock-lab/issues/39#issuecomment-6139247844)，不寫入本節。

### 版本、外部 pins 與上限

| 項目 | 內容 |
| --- | --- |
| 外部 policy | version `issue39-institutional-flow-to-volume-two-cutoffs-v1`；canonical 5,541 UTF-8 bytes（sorted keys、compact JSON、無尾 LF）；SHA-256 `00ab692d13bfb7ea242eb5d02dc361def40f51a0b4a583a173df265bd2fd910d`。由全局發布於 [#39 留言 6126200268](https://github.com/YiCheng0608/stock-lab/issues/39#issuecomment-6126200268)；產品常數 `POLICY_SHA256`／`POLICY_BYTES` 固定它 |
| profile／用途 | profile `free_public_local`；source_use `local_personal_noncommercial_institutional_flow_to_volume_ratio`；market TW/TPEx、ordinary stock、identity_as_of 2026-10-06；consumer `institutional-flow-volume-ratio-two-cutoffs-v1`，公式 `institutional-flow/v2-shares-per-share-volume` |
| 來源資料集 | FinMind `TaiwanStockInstitutionalInvestorsBuySell`（法人買賣，欄位 `date`、`stock_id`、`buy`、`sell`、`name`）與 `TaiwanStockPrice`（日線，成交量 `Trading_Volume`，股）供比率的分子與分母；`TaiwanStockTradingDate` 只供交易日曆 |
| 標的與日期 | TPEx 3105／3293／5274／5347／6488／6510／8069；區間 2026-09-01～2026-10-06（formal 24 個交易日）；截止日 2026-10-05、2026-10-06 |
| 請求 | 固定 15 個 GET，host 只有 `api.finmindtrade.com`，endpoint `https://api.finmindtrade.com/api/v4/data`。順序：#0 `TaiwanStockTradingDate`，#1～#7 `TaiwanStockPrice`，#8～#14 `TaiwanStockInstitutionalInvestorsBuySell`；個股依 3105、3293、5274、5347、6488、6510、8069；query 依序 `dataset`、`data_id`（日曆無）、`start_date`、`end_date`。日曆通過才取價格，七檔價格全過才取第一筆法人；不換 provider、日期或路由 |
| 請求標頭 | `Accept: application/json`、`Accept-Encoding: identity`、`Connection: close`、`User-Agent: stock-lab-issue39-local-ram/1` |
| 上限 | 每份 body 1 MiB、aggregate raw 8 MiB、retained-roots estimate 32 MiB；每 URL 20 s、整批 180 s；其餘同共同規則 |
| formal 參照 | formal 日曆、2026-10-06 七檔成交量與兩截止淨額 anchor 由產品從固定 blob `116bfab818fc5f72a650573c611d62b662372026:docs/SOURCE_REGISTRY.md`（SHA-256 `f27024ba1f4d5874610e3446cae34401dbeab4ea485706704e78cd4ef3844240`）的 [§31.2](#312-24日完整觀測日曆與20日金融集合)、[§32.2](#322-完整重驗與有限衍生)、§47.6（現行文 [§47.3](#473-原件驗證與五日分子計算)）解析；呼叫者必須提供該 blob，位元組不符即 `formal_blob_pin` 拒絕。這個 pin 指向 commit 內容，不隨本檔後續編修而變 |

### 用途、授權與署名

用途與權利界線見 [FinMind 來源共同規則](#finmind-來源共同規則)。Policy `unsupported`：`raw_disk_storage`、`redistribution`、`historical_pit`、`adjusted_prices`、`company_actions`、`trading_halt_comparability`、`twd_denominator`、`strategy_full_chain`、`api_ui_db`、`other_cutoffs`、`other_symbols`、`gross_flow_shape_anchor`。署名方式依共同規則：本節 policy 沒有固定完整署名文字，也沒有引用 FinMind 條款全文或條款版本，以 policy 的 `rights` 字串承擔（三個來源逐字相同，字串同共同規則所載）。

免費免 token 是文件推論（見共同規則），本節的文件依據：法人資料集依 FinMind Chip 頁（`https://finmind.github.io/tutor/TaiwanMarket/Chip/`，文件 GET 收據 [#9 留言 6124059360](https://github.com/YiCheng0608/stock-lab/issues/9#issuecomment-6124059360)），逐股 `data_id` 查詢沒有 backer／sponsor 標記，但文件沒有寫「可免 token」；日曆依 Technical 頁（收據 [#32 留言 6111856880](https://github.com/YiCheng0608/stock-lab/issues/32#issuecomment-6111856880)）。

| 項目 | qa1 |
| --- | --- |
| namespace | `issue39-seven-flow-to-volume-ratio-two-cutoffs-v1/qa1`（不與 #9 共用取得） |
| 使用者核准 | [#1 留言 6139204697](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-6139204697)（15 GET、一次性 NO-RETRY） |
| seal | [#39 留言 6139202306](https://github.com/YiCheng0608/stock-lab/issues/39#issuecomment-6139202306)；raw 579 B，SHA-256 `2e257d085a19b14c176d7f477adc79c512252be50156b5be7f715f8a67d5542c`；有效期 UTC 2026-10-13 05:52:00～06:30:00 |
| candidate | `78cd1f243d117b1f2b9245e82794d48a75e5876b` |
| QA 結果 | [#39 留言 6139247844](https://github.com/YiCheng0608/stock-lab/issues/39#issuecomment-6139247844)：成功 |

### 欄位對應、原件驗證與比率輸入

- **取得與傳輸**：與 [§49.3](#493-原件驗證與-last60summary-計算) 的取得與標頭條同一組規則（HTTP 200 才接受、identity 編碼、`application/json`、framing、重複身分標頭拒絕、strict UTF-8 無 BOM、`set-cookie` 不送出也不保存）；完整 EOF 與 raw hash 通過後才 parse。
- **交易日**：區間內回傳的日期須全為平日、含兩個截止日，且與 formal 24 個交易日（9 月 20 個、10 月至 10/06 共 4 個）完全相同；缺、多、由缺列推休市一律整批拒，發生在任何價格 GET 之前。
- **價格**：每檔 `{status, msg, data}`，`data` 恰 24 列，每列含 `date`、`stock_id`、`open`、`max`、`min`、`close`、`Trading_Volume`、`Trading_money`（可另含 `spread`、`Trading_turnover`，不採用）；`stock_id` 等於請求代號，日期集合等於 24 日；OHLC 為有限正值且上下界一致，成交量與成交額為正整數。OHLC、成交量或成交額為 0 的列整批拒收，不補 0、不縮窗（已接受風險，停牌不支援）。2026-10-06 七檔成交量須與 §32.2 anchor 逐值 exact。
- **法人**：每檔 `{status, msg, data}`，每列鍵恰為 `date`、`stock_id`、`buy`、`sell`、`name`；`stock_id` 等於請求代號；`buy`、`sell` 為非負 canonical int64，0 是正常值並保留；`name` 只接受 `Foreign_Investor`、`Foreign_Dealer_Self`、`Investment_Trust`、`Dealer_self`、`Dealer_Hedging`，每股每個正式日各恰 1 列（每檔 120 列），出現 `Dealer` 等其他名稱、缺列、重複或日期集合不等於 24 日即整批拒，不補 0。
- **欄位對應**：外資＝`Foreign_Investor`（外陸資，不含外資自營商）；投信＝`Investment_Trust`；自營商＝`Dealer_self`＋`Dealer_Hedging`；`Foreign_Dealer_Self` 驗結構但不計入。淨股數＝`buy`－`sell`（signed int64）。
- **單位**：股、scale 1，是 composite mapping 推論（policy `provider_literal_unit_annotation` 為 false），不是 FinMind 宣告；以七股 × 兩截止 × 四個淨股數（外資、投信、自營商、合計）共 56 個 §47.6 官方 TPEx 值，加 7 個 §32.2 的 2026-10-06 成交量，全部 exact 相等驗證，任一不符整批拒。不設 gross 形狀 anchor。
- **admission**：取得完成後狀態為 pending；須由獨立 oracle 在同一段 RAM 對 15 份 capture 全數 admit（綁定 15 份 receipt 的 SHA-256，real 路徑另綁定 QA holder、candidate 與 script SHA-256），才為 available，getter 與 consumer 才可用。failed、expired（租約至多 180 s）與 released 都拒用。
- **consumer**：`get_ratio_inputs(snapshot, symbol, cutoff)` 取截止日（含）向前 5 個交易日的淨股數與 20 個交易日的成交量（股），窗口不滿、對不齊即拒；`institutional_flow_volume_ratio_v1(snapshot, symbol, cutoff)` 以整數有理數計算比率，門檻 `ratio >= -3/1000` 以精確比較判定，不用浮點。
- **拒用**：建構 `FlowVolumeSource` 時 purpose 不等於固定 source_use 即回 `unsupported_purpose`，早於任何 GET。取得後：cutoff 不在兩個截止日或代號不在七股回 `unsupported_window_scope`；未傳 snapshot 回 `snapshot_required`；狀態不是 available（pending、failed、expired、released）回 `consumer_unavailable`。

### qa1 結果與 SPENT／NO-RETRY

- qa1 只執行一次，原 exit 0：15／15 個 GET 皆 HTTP 200、0 轉址；日曆與 24 日 formal 全等，56 個淨股數與 7 個成交量 anchor 全部 exact，14 個比率（兩截止 × 七股）與獨立精確 oracle 一致，錯誤 admission 皆被拒，release 後 consumer 全部撤銷，guard `blocked 0`。
- 真實回應與 gate 假設一致（一次觀測，不是 FinMind 對形狀的承諾）：三個資料集（日曆、價格、法人）的 15 筆匿名請求都是 HTTP 200，沒有 401／402／403；每檔法人 body 恰 120 列、每列欄位恰為上列五鍵。
- 額度已用盡，seal 作廢。SPENT／NO-RETRY 登錄於 [#1 留言 6139264250](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-6139264250)；同 namespace 不得再取，再取規則見共同規則。

### 未驗與限制

- **範圍**：只涵蓋 7 檔上櫃股、2026-10-05 與 2026-10-06 兩個截止日、FinMind 免 token 公開 API；不證其他標的、日期或上市股票。只涵蓋 strategy 法人 gate（5 日淨股數 ÷ 20 日均量）；hot_group 的 20 日成交量合計變體不在 policy 範圍。
- **只在本地 RAM**：沒有落盤，也沒有接 DB、`backend/worker/pipeline.py` 的 DB 路徑、API 或 UI；那些層的 AC 不因本節而通過。DB 路徑的選窗與本模組的 24 日日曆全等檢查不同，見 [V1_SPEC](V1_SPEC.md) 的已知實作偏差。
- **anchor 覆蓋有限**：24 日中，只有 2026-10-06 的成交量與兩個截止五日窗口的淨股數有獨立 anchor，其餘各日只做結構驗證；單位是推論。
- **補計與穩定性**：FinMind 文件註明數值可能於初次公布後微幅更新，本節只採淨股數，補計若使淨額改變，anchor 會整批拒（fail-closed，已接受風險）。日後更正不涵蓋；匿名請求一次成功不證限流、條款或長期穩定。
- **未在真實來源驗到**：租約 expiry、gzip／br、401／402／403 與零價列的真實路徑未觸發，只有合成證據；防護性質見共同規則。
- **版本與依賴**：本節描述 candidate `78cd1f243d117b1f2b9245e82794d48a75e5876b` 的契約與 qa1 結果；其後程式、policy 或驗收語意變動須重驗並更新本節。本節不宣稱解除母單 #21 的整體 AC。

## 52. #7：七股普通收盤與交易日曆的日期／時區語意契約

2026-10-12。#7 以 [§49](#49-32-qa1qa2七股-finmind-nominal-ohlcv-日線-last60-與兩截止-raw-算術issue32-seven-nominal-ohlcv-two-cutoffs-v1) 已整合的 FinMind `TaiwanStockTradingDate`／`TaiwanStockPrice` 取得與驗證路徑為基礎，取得七股截至 2026-10-06 的普通股收盤，只把 60 個交易日的正規化收盤保存為私人本地衍生值，供讀回使用。產品 `backend/app/ordinary_close_source.py`（沿用但不改 `backend/app/ohlcv_history_source.py`），測試 `backend/tests/test_ordinary_close_source.py`。本節登錄日期／時區語意、取得與 policy pin、私人保存與讀回契約；不改寫 §49 的 policy、pins、capture 或 default，也不含任何取回的價格列、原始 body 或衍生數值。缺口與裁定見 [#7 QA 留言 6123856560](https://github.com/YiCheng0608/stock-lab/issues/7#issuecomment-6123856560)（AC-1 缺口 1）、[全局裁定 6124105434](https://github.com/YiCheng0608/stock-lab/issues/7#issuecomment-6124105434)（D1、D5、D6）與 [policy v1 裁定 6125706492](https://github.com/YiCheng0608/stock-lab/issues/7#issuecomment-6125706492)（E1～E5、P1～P3）。

### 日期欄位

`TaiwanStockTradingDate` 與 `TaiwanStockPrice` 每列的 `date` 是臺灣市場（Asia/Taipei）交易日的曆日，格式為 ISO `YYYY-MM-DD`，不含時間與時區偏移。它只標示「哪一個交易日」，不是 UTC 日期，也不是資料的發布日、取得日或修訂日。消費端把它當曆日使用（判斷交易日、排序、取窗口），不得補時分、不得當成 UTC 零時，也不得依時區換算。

### 時間欄位

receipt 的 `request_started_utc`、`observed_utc` 與 `saved_at` 是以 `+00:00` 結尾的 aware UTC，字串須與 Python `datetime.isoformat()` 的輸出逐字相同，例如 `2026-01-02T03:04:05.678901+00:00`（微秒為 0 時不帶小數）。讀回端把解析結果重新序列化後逐字比對，所以 `Z` 結尾、非 UTC 偏移、無時區，或不是 `isoformat()` 形式的小數位，一律拒收（`saved_time`）。它們記錄這次取得何時發生，與交易日無關：UTC 16:00 起已是臺北的隔日，所以觀測時間不得用來推交易日，`date` 也不得補成時刻。兩者都不推 publication、first availability 或 revision；三者維持 `unknown`，`historical_pit` 不支援（[§49.3](#493-原件驗證與-last60summary-計算)、[§49.7](#497-未驗與限制)）。

### 對齊證據

- **交易日曆**：FinMind 8～10 月 45 日與 formal 45 日完全相同（產品 gate 與獨立 oracle 各自通過），所以這 45 日 FinMind 的曆日與 formal 交易日曆沒有位移（[§49.3](#493-原件驗證與-last60summary-計算)、[§49.6](#496-qa2成功取得與驗證結果)）。
- **價格列**：FinMind `date` 為 2026-10-06 的列，七股 × 開高低收量額六欄共 42 個 anchor 與 TPEx 同日數值逐值 exact（同上）。
- **收據**：以上是 #32 qa2 的收據（[留言 6115359522](https://github.com/YiCheng0608/stock-lab/issues/32#issuecomment-6115359522)，原始輸出 [留言 6115344851](https://github.com/YiCheng0608/stock-lab/issues/32#issuecomment-6115344851)）；價格值已隨 release 清除，本節不重現。
- **性質**：這是對齊證據，不是 provider 的逐字聲明；policy v3 沒有時區欄位。語意由上列證據支持，證據範圍之外不外推。

### 取得與 policy pin

| 項目 | 內容 |
| --- | --- |
| 外部 policy | version `issue7-ordinary-close-saved-seven-v1`；canonical 5,173 UTF-8 bytes（sorted keys、compact JSON、無尾 LF）；SHA-256 `f7659362cd3056413545d48a40a2e89bc97b810dc9c5535a4c8bdca41fcb9968`。由全局發布並貼於 [#7 留言 6125706492](https://github.com/YiCheng0608/stock-lab/issues/7#issuecomment-6125706492)，全文以該留言為準，測試檔 `backend/tests/test_ordinary_close_source.py` 另存獨立字面值 `V1_POLICY` 作對照；產品常數 `POLICY_SHA256`、`POLICY_BYTES` 只存 pin，產品不能由被測 policy 自建 expected |
| profile／用途 | profile `free_public_local`；source_use `local_personal_noncommercial_private_derived_close_window`；consumer `ordinary-close-saved-window-v1`；market TW/TPEx、ordinary stock、identity_as_of 2026-10-06 |
| 標的與日期 | 七股同 [§49.1](#491-版本外部-pins-與上限)；**一份 policy 只對應一個 cutoff：2026-10-06**；窗口 2026-07-01～2026-10-06；`beyond_formal_trading_dates` 固定為空；其他 cutoff 列為 `other_cutoffs`，不支援 |
| 請求與傳輸 | 固定 8 個 GET（交易日 1、七股價格依代號升序 7）；host、endpoint、query 順序、請求標頭（含 `User-Agent: stock-lab-issue32-local-ram/1`）、framing、上限與首敗即停都沿用 [§49.1](#491-版本外部-pins-與上限)、[§49.3](#493-原件驗證與-last60summary-計算)。與 policy v3 的 `acquisition.*`、`response_shape.*` 逐葉比對只差 `acquisition.namespace`（全局核對，見上列留言） |
| 交易日曆 | 參數化版本的 [§49.3](#493-原件驗證與-last60summary-計算) gate：日期須為平日、含 cutoff、cutoff（含）以前至少 60 個交易日、8～10 月與 formal 45 日完全相同、七股日期集合各自等於交易日集合、cutoff 之後無日期；錯誤碼沿用 #32 |
| 一次性額度 | namespace `issue7-ordinary-close-saved-seven-v1/qa1`；整批只一次，attempted 即 SPENT，程序內 ledger 無 reset 或 retry。成功後仍是 pending，須獨立 oracle admission 才 available（admission 綁 8 份 receipt SHA-256、`closes_sha256` 與 QA holder／candidate／script）；租約不超過批次期限，release 後拒用 |
| seal | 真實路徑另須 `FinancialStart` 與 `ExecutionBinding`（holder effort `xhigh`，且不在 seal 角色內）；seal 須是 #7 的新明示留言，編號大於 policy 發布留言 6125706492（`SEAL_COMMENT_FLOOR`，是門檻不是授權）。pin 或 seal 任一不符，在任何 GET 之前拒絕 |

### 私人保存

保存的是衍生值，不是原件：每股 60 個交易日（含 cutoff）的正規化收盤與日期，加一份 receipt。不保存 raw body，也不保存開、高、低、量、額。只寫檔案、不寫資料庫；`save` 之外沒有寫入。

| 項目 | 契約 |
| --- | --- |
| root | 環境變數 `STOCK_ORDINARY_CLOSE_PRIVATE_ROOT` 是唯一來源；未設、非絕對路徑或含 `..` 都不寫（`root_unset`、`root_invalid`）。root 由核定的私人本地路徑提供，不在 repo 內 |
| 版面 | `<policy_version>/<cutoff>/{closes.json,receipt.json}`；storage schema `ordinary-close-saved/v1`、receipt schema `ordinary-close-receipt/v1`；兩檔皆 canonical UTF-8 JSON（sorted keys、compact） |
| `closes.json` | `schema`、`cutoff`、`count`（60）、七股 `symbols`、60 個 `trading_dates`（唯一遞增平日、末日＝cutoff）、`counts`、每股 60 列 `[date, close]`。close 是正的十進位字串：無指數、無尾隨 0、≤ 6 位小數、整數 ≤ 13 位，超過整批拒（`close_representation`）。20／21 日窗口取這 60 列的尾端 |
| `receipt.json` | 8 個 GET 各自的 URL、status、content-type／content-encoding、請求與觀測時間（UTC）、body SHA-256 與 bytes、receipt SHA-256；policy 版本／SHA-256／bytes；`ordinary_close_source.py` 與 `ohlcv_history_source.py` 的 SHA-256；`closes.json` 的 SHA-256 與 bytes；attribution、rights、limitations；`saved_at`（UTC）；`publication_time`、`first_availability`、`revision_time` 固定 `unknown` |
| 上限 | `closes.json` ≤ 65,536 B（64 KiB）、`receipt.json` ≤ 32,768 B（32 KiB）；root 內 ≤ 2 個 bundle、≤ 4 個檔案、合計 ≤ 196,608 B（192 KiB）。超過即拒（`quota_bundles`、`quota_files`、`quota_bytes`）；root 內有任何外來或半成品項目也拒（`root_entries_invalid`） |
| 出版 | 先寫 root 下的暫存目錄（`.staging-<隨機>`，每檔 `O_EXCL` 並 fsync），再以 rename 原子換成 `<policy_version>/<cutoff>`，不覆寫既有 bundle。已存在且 `closes.json` 位元組與去除 `saved_at` 的 receipt 都相同回 `idempotent`，不同則 `final_conflict`。出版後以讀取端的同一份程式回讀並逐位元組比對；失敗時回收暫存與本次建立的目錄 |

### 讀回與驗證

`load_saved_closes(root, policy_version, cutoff, *, pins=None)` 唯讀、不取源，也不 fallback 到其他版本或截止（缺 bundle 回 `saved_missing`）；`pins` 預設為產品常數。下游讀用（如 #8）呼叫 `load_saved_closes` 時不得自帶 `pins`，自帶的 `pins` 只供邊界測試；`pins` 綁的是 policy 摘要，不是簽章，receipt 不能當成不可竄改的證據。每次讀取都由讀取端完整重驗，不信任寫入端，新程序讀回亦同：

- **路徑**：root、版本目錄、bundle 目錄須是真目錄，不得是 symlink 或 reparse point；bundle 內恰有兩個檔，各自不超過上限。
- **內容**：schema 與固定欄位、policy 版本與 pin（SHA-256、bytes）、cutoff 一致；60 個交易日唯一遞增、平日、末日＝cutoff；七股日期集合相同；每個 close 都是正規化正值。
- **receipt**：8 個 GET 的 URL、status 200、完整 EOF、content-type／content-encoding、時間順序與各自的 receipt SHA-256 重算相符；`closes.json` 的 SHA-256 與 bytes 和 receipt 引用一致。

任一不符整體拒絕，不修補、不補值。回傳 `SavedCloses`（含兩檔 SHA-256）；`window(symbol, count)` 取尾端 `count`（1～60）列，20 與 21 日窗口由此取得。

### 範圍與限制

- 逐日對齊只涵蓋 8～10 月的 formal 45 日。7 月沒有獨立於 FinMind 的第二來源，2026-07-10 缺日沒有原因證據；cutoff 2026-10-06 的 60 日窗口自 2026-07-13 起、不含該缺日，其中 7/13～7/31 只有 FinMind 一個日曆來源（由交易日序列推得，見 [§49.7](#497-未驗與限制)）。
- 身分與單位只錨定 2026-10-06（全局裁定 D5）；其他日期沒有逐日核對，policy 的 `unsupported` 不因本節放寬。
- 條款頁未固定版本或雜湊，接受 [§49.2](#492-用途授權與署名) 的免費使用推論風險（全局裁定 D6，與 FinMind 為主一致）。
- 保存的是 FinMind provider-reported nominal 收盤；調整價、公司行動、停牌可比性、PIT 與 revision 保證不支援（policy `unsupported`），其他 cutoff 與 raw body 保存、再散布也不支援。
- close 超過 6 位小數或整數 13 位的上限時整批拒（全局裁定 E4，列為已知風險）。
- policy 的 `rights`、`attribution` 字串是否充分屬使用者決策，核准後才用於真實取得；改字即重發 policy、重算 pin、重驗受影響項（全局裁定 P1）。

### 版本邊界

- 本節不含任何取回的價格列、原始 body 或衍生數值；取得與讀回的收據、數值與實測紀錄留在 [#7](https://github.com/YiCheng0608/stock-lab/issues/7) 的 QA 留言，不寫入本文。
- 本節是契約登錄，不宣稱解除 #8 或 #20 的依賴；依賴是否解除由全局依整合版本判定。
- 本節描述 adapter 與保存契約；其後程式、policy 或驗收語意變動須重驗並更新本節。

## #98：七股 FinMind 交易日曆、停復牌間接證據與公司行動因子（issue98-tpex-seven-calendar-actions-v2）

2026-10-14。#98 以 FinMind 公開 API v4 取得七股（TPEx 普通股）2026-07-01～2026-10-12 的交易日、日價格與除權息、減資、分割資料，在本地導出交易日曆、個股日狀態與公司行動價格因子，只把衍生值保存到私人 root，供下游（如 #38）明示資料版本後讀用 raw／adjusted basis。產品 `backend/app/tpex_calendar_actions_source.py`（沿用 [§49](#49-32-qa1qa2七股-finmind-nominal-ohlcv-日線-last60-與兩截止-raw-算術issue32-seven-nominal-ohlcv-two-cutoffs-v1) 的 #32 取得合約，不改 `backend/app/ohlcv_history_source.py`），測試 `backend/tests/test_tpex_calendar_actions_source.py`。本節只管理這個新 namespace，不提升也不改寫其他節的 policy、pins、capture 或 default。取得過程與 QA 收據保存在 [#98](https://github.com/YiCheng0608/stock-lab/issues/98)，下列為契約與結果摘要並附留言編號，共同規則見 [FinMind 來源共同規則](#finmind-來源共同規則)。本節不含任何取回的價格、因子或原始 body；原件只在 RAM，已隨 release 清除。

### #98 版本、外部 pins 與上限

| 項目 | 內容 |
| --- | --- |
| 外部 policy | version `issue98-tpex-seven-calendar-actions-v2`；canonical 10,136 UTF-8 bytes（sorted keys、compact JSON、無尾 LF）；SHA-256 `ef10c3c71b4c643365bafc164d7324a88399b9ec27773c0438ef061b95feb794`。由全局發布於 [#98 留言 6170250977](https://github.com/YiCheng0608/stock-lab/issues/98#issuecomment-6170250977)，位元組取自工程收據 [6170207842](https://github.com/YiCheng0608/stock-lab/issues/98#issuecomment-6170207842) 的單行 JSON，不改任何位元組；產品常數 `POLICY_SHA256`／`POLICY_BYTES` 固定它，產品不能由被測 policy 自建 expected pin。相對 v1，v2 移除面額變更資料集（GET 44 → 37）並改為偵測式拒用（新增 `checks.par_value_change` 與 `unsupported` 的 `par_value_change_factor`），傳輸、response_shape、calendar、storage、symbols、window 逐值不變，逐鍵 diff 見發布留言 |
| 已被取代的 v1 | policy v1（10,257 B，SHA-256 `fcdc77c4dd0c752da9a75bc3f5fe334d9ab61edfe8c903849af6466db55d2724`，[發布留言 6139122796](https://github.com/YiCheng0608/stock-lab/issues/98#issuecomment-6139122796)，44 GET）已被 [AC 修訂 1](https://github.com/YiCheng0608/stock-lab/issues/98#issuecomment-6169958046) 取代；v1 的 policy 與 namespace `issue98-tpex-seven-calendar-actions-v1/qa1` 都被產品拒絕，不再接受 |
| namespace | `issue98-tpex-seven-calendar-actions-v2/qa1`（一次性額度；v1 的額度已 SPENT，見下） |
| seal floor | 產品常數 `SEAL_COMMENT_FLOOR` ＝ 6170250977：seal 須是 #98 的新明示留言且編號大於它（門檻，不是授權）。issuer、coordinator、implementer、QA holder 的 session 身分由 seal 帶入，產品只驗形狀與互異（holder effort `xhigh` 且不在 seal 角色內），不認證 GitHub 或 runtime 身分，須由獨立 QA 與任務統籌另行讀回 |
| profile／用途 | profile `free_public_local`；source_use `local_personal_noncommercial_private_derived_calendar_actions`；consumer `tpex-calendar-actions-read-v1`；market TW/TPEx、ordinary stock、identity_as_of 2026-10-06；讀用端 market 只收 `TPEx`、security_type 只收 `ordinary_share` |
| 標的與期間 | TPEx 3105 穩懋／3293 鈊象／5274 信驊／5347 世界／6488 環球晶／6510 精測／8069 元太；2026-07-01～2026-10-12；`TaiwanStockDividend` 查到 2026-12-31（其 `date` 是基準日，晚於除權息日） |
| 請求 | 固定 37 個 GET，host 只有 `api.finmindtrade.com`，endpoint `https://api.finmindtrade.com/api/v4/data`，query 依序 `dataset`、`data_id`（日曆與股票資訊無）、`start_date`、`end_date`（股票資訊兩者皆無）。順序：日曆 1 → 價格 7 → 除權息結果 7 → 除權息公告 7 → 減資 7 → 分割 7 → 股票資訊 1；每組七檔依 3105、3293、5274、5347、6488、6510、8069 升序；日曆先取，通過 gate 才取其餘；不換 provider、日期或路由。37 個 URL 全文以 policy `sources` 為準 |
| 標頭、framing 與上限 | 標頭（含 `User-Agent: stock-lab-issue32-local-ram/1`）、framing、單份 body 1 MiB、retained-roots estimate 32 MiB、每 URL 20 s 同 [§49.1](#491-版本外部-pins-與上限)；本節差異：aggregate raw 16 MiB（16,777,216 B）、整批 600 s（cooperative）、租約至多 180 s。redirect 0、retry 0、每 URL 最多 1 次、首敗即停且 attempted 即 SPENT；只在 RAM |
| 固定 formal 參照 | 日曆 gate 的 formal 45 日與 2026-10-06 的 42 個 anchor（[§32.2](#322-完整重驗與有限衍生)）由產品從固定 blob `d8918bc6491ec8ef65874979cf88d1322df2da43:docs/SOURCE_REGISTRY.md`（SHA-256 `b5ea9605c75add4bfa5581672d3778ac2851a29ac599e3e0b9e938880f42abde`，同 [§49.1](#491-版本外部-pins-與上限)）解析；呼叫者必須提供該 blob，位元組不符即拒絕 |
| candidate | v2/qa1 真實取得所用 candidate `33db5803f320ac465b21b2f6f0eed55d4e43cebf`（v1/qa1 為 `7af4c30d6373329c8e12cfc356b747b95112119d`） |

### #98 資料集、欄位型別與原件驗證

七個資料集（編號沿用 #98 的來源盤點收據 [6135101980](https://github.com/YiCheng0608/stock-lab/issues/98#issuecomment-6135101980)，F6b 面額變更已移除）。必要欄位指鍵須存在（`N`、`T` 型別的值可為 null）；未列的額外鍵容許，只記錄欄名（F1 例外：每列鍵恰為 `date`）。

| 編號 | 資料集 | GET | 期間 | 必要欄位：型別 | 選填欄位：型別 |
| --- | --- | --- | --- | --- | --- |
| F1 | `TaiwanStockTradingDate` | 1 | 全期間 | `date`:D | — |
| F2 | `TaiwanStockPrice` | 7 | 全期間 | `date`:D、`stock_id`:S、`open`／`max`／`min`／`close`:P、`Trading_Volume`／`Trading_money`:I | `spread`:N、`Trading_turnover`:i |
| F3 | `TaiwanStockDividendResult` | 7 | 全期間 | `date`:D、`stock_id`:S、`before_price`／`after_price`／`reference_price`:N | `stock_and_cache_dividend`:N、`stock_or_cache_dividend`:A、`max_price`／`min_price`／`open_price`:N |
| F4 | `TaiwanStockDividend` | 7 | 2026-07-01～2026-12-31 | `date`:D、`stock_id`:S | `StockExDividendTradingDate`／`CashExDividendTradingDate`／`AnnouncementDate`:d；`StockEarningsDistribution`／`StockStatutorySurplus`／`CashEarningsDistribution`／`CashStatutorySurplus`／`TotalNumberOfCashCapitalIncrease`／`CashIncreaseSubscriptionRate`／`CashIncreaseSubscriptionpRrice`:N；`AnnouncementTime`:A |
| F5 | `TaiwanStockCapitalReductionReferencePrice` | 7 | 全期間 | `date`:D、`stock_id`:S、`ClosingPriceonTheLastTradingDay`／`PostReductionReferencePrice`:N | `LimitUp`／`LimitDown`／`OpeningReferencePrice`／`ExrightReferencePrice`:N、`ReasonforCapitalReduction`:A |
| F6a | `TaiwanStockSplitPrice` | 7 | 全期間 | `date`:D、`stock_id`:S、`before_price`／`after_price`:N | `type`:A、`max_price`／`min_price`／`open_price`:N |
| F9 | `TaiwanStockInfo` | 1 | 不帶 `data_id` 與日期 | `stock_id`:S、`type`:T、`date`:d | `industry_category`／`stock_name`:A |

- **型別代號**：D 嚴格 ISO 日期；d 寬鬆日期（空值或無法解析時記為未解析，不拒整批）；S 非空字串；T 可為 null 的字串；A 可為 null 的純量，以文字保存；P 非負數；N 可為 null 的數；I 非負 int64；i 可為 null 的非負 int64。
- **取得與傳輸**：與 [§49.3](#493-原件驗證與-last60summary-計算) 的取得與標頭條同一組規則（HTTP 200 才接受、identity 編碼、`application/json`、framing、重複身分標頭拒絕、strict UTF-8 無 BOM、`set-cookie` 不送出也不保存）；完整 EOF 與 raw hash 通過後才 parse。回應 envelope 恰為 `status`（整數 200）、`msg`（`"success"`）、`data`（列表）三鍵。`data: []` 不是首敗，只表示該資料集沒有列；結構、型別、必要欄位或傳輸不符才整批首敗。
- **先驗全部、再取範圍**：所有回傳列先驗結構，之後才捨棄期間外的列，所以來源是否依 `start_date`／`end_date` 過濾都不影響結果。價格列的 `stock_id` 須等於請求代號；事件資料集中其他代號的列只計入 `foreign_rows`，不採用。
- **免費使用是文件推論**：依據文件核對收據（[6135101980](https://github.com/YiCheng0608/stock-lab/issues/98#issuecomment-6135101980)，DataList、Fundamental、Technical 三頁；policy `documentation` 固定後兩頁的 SHA-256）。`TaiwanStockSuspended`（停牌）與 `TaiwanStockPriceAdj`（還原價）標「只限 backer、sponsor 會員使用」，免費方案不能用，本節不使用；F5 不帶 `data_id` 的全市場查詢限 backer、sponsor 會員，所以 F2～F6a 一律逐檔帶 `data_id`。上列資料集沒有會員標記，但文件沒有寫「可免 token」，401、402、403 或任何要求付費、登入的回應是首敗。`TaiwanStockParValueChange` 不取得：v1 的第 37 個 GET 即此資料集，回應非 200，依 AC 修訂 1 移除。F4 的四個金額欄名是 Fundamental 頁的 schema 名稱；F9 的 `type` 值 `tpex` 依 Technical 頁「資料表同時保留興櫃與 twse／tpex 列」的說明，字面值要等真實回應才能確認（結果見下）。

### #98 用途、授權與署名

用途只限免費公開、本地個人非商用研究。與共同規則不同的是：依使用者決策（[#1 留言 6135194709](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-6135194709) D6）小量衍生值（日曆、日狀態、事件、因子與核對結果）可保存到私人 root，原始回應不落盤、不發布、不鏡像、不再散布。同一決策也定下：只用 FinMind 免費資料（D1、D3）、期間終點固定 2026-10-12（D2）、遇到不支援的事件照實拒用而七檔承諾不縮（D4）。

Policy `unsupported`（逐字）：`historical_pit`、`publication_time`、`first_availability`、`revision_guarantee`、`positive_suspension_fact`、`paid_subscription`、`par_value_change_factor`、`provider_adjusted_prices`、`other_symbols`、`other_markets`、`other_dates`、`raw_body_storage`、`redistribution`、`actionable_strategy`、`plan`、`trading`、`historical_simulation`。`publication_time`、`first_availability`、`revision_time` 固定 `unknown`。

權利字串（policy `rights`，逐字）：`FinMind personal noncommercial local private derived calendar and corporate actions; attribution; no raw body storage, redistribution or mirror`。署名字串（policy `attribution`，逐字）：`Source: FinMind (finmindtrade.com) trading dates, daily prices, dividend results, dividends, capital reductions, split reference prices and stock info; provider-reported values kept as private local derived facts; raw bodies not stored or redistributed`。兩者固定在被 pin 的 policy 內，隨 policy SHA-256 被 seal 綁定並寫入保存的 receipt；FinMind 是服務提供者，不是官方直接來源，條款頁未固定版本。權利是否充分屬使用者決策，QA 只核對它被 seal 綁定。

### #98 日狀態、核對規則與因子

- **日曆 gate**（早於任何其他 GET）：F1 所有回傳列先驗結構（唯一、遞增的 ISO 日期），再取 2026-07-01～2026-10-12 的列。期間內日期須全為平日、含 2026-10-06，且 8～10 月至 2026-10-06 的部分與 formal 45 日（8 月 21、9 月 20、10 月 4）完全相同（見 [§49.3](#493-原件驗證與-last60summary-計算)）；7 月與 2026-10-06 之後的日期照來源回傳接受，不限天數，不從缺平日推休市。2026-10-06 之後的日期另存為 `calendar_after_formal`。日期是臺灣市場（Asia/Taipei）交易日的曆日，不是 UTC（[§52](#52-7七股普通收盤與交易日曆的日期時區語意契約)）。
- **日狀態（停復牌只有間接證據）**：日曆上的交易日，若該檔沒有價格列、或 OHLC 全 0、部分為 0、上下界不一致，該檔該日為 `incomparable`（理由 `missing_row`、`ohlc_zero`、`ohlc_partial_zero`、`ohlc_bounds`）；不讓批次失敗，也不宣稱為停牌（`positive_suspension_fact` 不支援）。價格列落在日曆之外，或整檔沒有價格列，該檔 `refused`。
- **身分**：2026-10-06 的六欄 anchor（開高低收量額，[§32.2](#322-完整重驗與有限衍生)）須與價格列逐值相等，否則該檔 `refused`（`identity_anchor_mismatch`）。F9 取該檔 `date` 最新的列，`type` 須為 `tpex`；沒有列、最新列不唯一或 `type` 不符，該檔 `refused`（`info_missing`、`info_ambiguous`、`market_type_not_accepted`）。
- **spread 參考價核對與語意示範**：FinMind 把 `spread` 寫成「漲跌幅」而未說明是價差或比例，所以語意要由資料證明。隱含參考價 ＝ `close − spread`，須等於前一個可比日的收盤；不等的日子若有事件（任何種類，含已拒用者）記為被事件解釋，否則記為未解釋。示範成立的條件：七檔合計至少一個事件日的隱含參考價不同於前一可比收盤，且該檔吻合日數至少 20；否則該檔 spread 狀態為 `semantics_unverified`。有未解釋差異為 `unexplained_change`，其餘為 `consistent`。狀態不是 `consistent` 的檔，adjusted 整檔拒用（raw 不受影響，批次不首敗）。
- **面額變更 fail-closed**：面額變更資料集不取得、不計算因子。面額變更日的參考價跳動沒有事件可解釋，成為未解釋差異，該檔 adjusted 拒用（AC 修訂 1）。
- **除權息因子**：因子 ＝ `(P−C)/P × 1/(1+Rf)`（公式來源見 [§6.3](#63-tpex-corporate-action-mapping)）。P 取 F3 `before_price`；C（現金）與 Rf（股票股利 ÷ 面額 10 元）取 F4 中除息日或除權日等於該日的列：現金部分只在除息日等於該日時計入，C ＝ 現金盈餘配息＋現金公積配息；股票部分只在除權日等於該日時計入，Rf ＝（股票盈餘配股＋股票公積配股）÷ 10。面額 10 元是推論。F3 與 F4 對不上或有歧義時事件拒用。
- **減資與分割因子**：因子 ＝ `after_reference / before_close`，減資取 F5 `PostReductionReferencePrice / ClosingPriceonTheLastTradingDay`，分割取 F6a `after_price / before_price`。
- **參考價互核**：除息因子隱含的參考價 R ＝ `(P−C)/(1+Rf)`，須與 F3 `reference_price` 的差嚴格小於一個 tick，且當日有可比價格列與 `spread` 時，須與 `close − spread` 的差也嚴格小於一個 tick；減資與分割的 `after_reference` 須與 `close − spread` 的差嚴格小於一個 tick，當日沒有可比列則 `factor_reference_unverified`。tick 取被觀察到的參考價（F3 `reference_price` 或 `close − spread`）所在級距，級距表（`0=1/100`、`10=1/20`、`50=1/10`、`100=1/2`、`500=1`、`1000=5`，下界含）出處是 [§50.2](#502-規則值與原文定位)（#97）。官方未說明參考價的捨入方式，所以容差是「嚴格小於一個 tick」而不是相等。未過即事件拒用（`factor_reference_mismatch`），不讓批次失敗。
- **其他拒用**：現金增資欄位為正（paid subscription）→ 事件拒用，不估參數；同一日多個事件 → 全部拒用（`same_day_multiple_events`）；事件日不在日曆（`event_date_not_trading_day`）；F4 有除權息日但 F3 無結果（`announced_without_result`，理由 `dividend_result_missing`）。其餘事件層理由：`event_duplicate_conflict`、`event_price_invalid`、`dividend_terms_unmatched`、`dividend_terms_ambiguous`、`dividend_terms_missing`、`dividend_terms_invalid`、`paid_subscription_unsupported`、`paid_subscription_fields_missing`、`cash_exceeds_price`、`factor_unavailable`。F4 日期無法解析、有金額而無除權息日，或窗口內除權息的資本增資欄位缺漏，該檔 adjusted 整檔拒用（`f4_date_unparsed`、`f4_ex_date_unknown`、`paid_subscription_fields_missing`）。
- **adjusted 可讀範圍**：`supported_from` ＝ 該檔最晚一件已拒用事件的日期，沒有則為日曆首日；adjusted 整檔拒用時為空。日期早於 `supported_from` 的 adjusted 讀取被拒，事件日當天與之後不受該事件影響。因子是該日之後所有事件因子之積。

### #98 私人保存與讀用

保存的是衍生值，不是原件：不保存原始 body 與逐日價格列；事件的前價、參考價與因子以最簡有理數字串保存（私人本地）。只寫檔案、不寫資料庫。

| 項目 | 契約 |
| --- | --- |
| root | `%LOCALAPPDATA%/taiwan-stock-research/tpex-calendar-actions-issue98`（本單專用，不與 #7 共用），由產品函式 `private_root()` 在呼叫時讀環境變數 `LOCALAPPDATA` 取得；import 時不讀環境、不做 I/O，這是模組內唯一的環境讀取。`LOCALAPPDATA` 未設或空字串為 `root_unset`，相對路徑、含 `..` 或 NUL 為 `root_invalid`（Windows 上磁碟機部分須為 `X:` 或完整 UNC `\\server\share`，server 與 share 皆非空，否則同為 `root_invalid`：沒有磁碟機的有根路徑如 `\foo`、`/foo` 相對於目前磁碟機，不完整 UNC 如 `\\`、`\\srv`、`\\srv\`、`//srv` 會把子目錄名當成他機的共用名稱），皆 fail-closed：不 fallback 到其他變數或路徑、不寫檔。預設 transport 的 `save` 只能寫此 root、`load_saved` 省略 root 時讀此 root；邊界 transport 須自帶 root 且不得等於它（`save` 兩個分支都先解析此 root，解析失敗即拒）；明示 root 的 `load_saved(root)` 不讀環境。外部 policy v2 的 `storage.root` 是位元組已釘選的歷史字面值（產品常數 `POLICY_STORAGE_ROOT`），只用於 policy expected 的逐值比對，不放寬、不改釘選，也不是讀寫目標，與執行期 root 不綁定；只有在產生該字面值的使用者設定檔下，兩者才指向同一目錄 |
| 版面 | `<policy_version>/<window_end>/{data.json,receipt.json}`，即 `issue98-tpex-seven-calendar-actions-v2/2026-10-12/`；storage schema `tpex-calendar-actions-saved/v1`、receipt schema `tpex-calendar-actions-receipt/v1`；兩檔皆 canonical UTF-8 JSON（sorted keys、compact） |
| `data.json` | `schema`、`window`、`calendar`、`calendar_after_formal`、`spread_semantics`（`demonstrated`、`evidence`）、`observed_fields`（各資料集實際出現的欄名）、七檔 `symbols`（`status`、`refusal_reasons`、`info`、`incomparable_days`、`spread_check`、`events`、`adjusted`、`foreign_rows`）。事件含種類（`ex_dividend`、`capital_reduction`、`split`、`paid_subscription`、`announced_without_result`）、日期、公告日期與時間、前價、參考價、因子、公式、trace、`supported` 與 `reasons` |
| `receipt.json` | 37 個 GET 各自的 URL、status、content-type／content-encoding、請求與觀測時間（UTC，`isoformat()` 形式）、body SHA-256 與 bytes、receipt SHA-256；policy 版本／SHA-256／bytes；產品檔與 `ohlcv_history_source.py` 的 SHA-256；`data.json` 的 SHA-256 與 bytes；`data_version`；`attribution`、`rights`、`limitations`；`saved_at`；`publication_time`、`first_availability`、`revision_time` 固定 `unknown` |
| 上限 | `data.json` ≤ 131,072 B、`receipt.json` ≤ 65,536 B；root 內 ≤ 1 個 bundle、≤ 2 個檔案、合計 ≤ 196,608 B，超過即拒（`quota_bundles`、`quota_files`、`quota_bytes`）；root 內有外來或半成品項目也拒（`root_entries_invalid`） |
| 准入與出版 | 取得完成為 pending；須獨立 oracle admission 才 available，才能 `save`。admission 綁 37 份 receipt 的 SHA-256（依請求序）、`data.json` 的 SHA-256 與日曆／價格／事件三個列數，real 路徑另綁 QA holder、candidate 與 script SHA-256。先寫 root 下的暫存目錄（每檔 `O_EXCL` 並 fsync），再以 rename 原子換成最終目錄，不覆寫；已存在且 `data.json` 與去除 `saved_at` 的 receipt 都相同回 `idempotent`，不同則 `final_conflict`。出版後以讀取端的同一份程式回讀並逐位元組比對 |
| `data_version` | `tpex-calendar-actions-data/v1:` ＋ `data.json` 位元組的 SHA-256（小寫十六進位）；`receipt.json` 記同一值，讀取時須相符。資料變動即版本變動 |

讀用只經 `load_saved(root=None, *, pins=None)`：唯讀、不取源、不 fallback 到其他版本；`pins` 預設為產品常數，自帶只供邊界測試，且綁的是 policy 摘要，不是簽章，receipt 不能當成不可竄改的證據。每次讀取都由讀取端完整重驗，新程序讀回亦同：路徑（root、版本目錄、bundle 目錄須是真目錄，不得是 symlink 或 reparse point，恰有兩個檔且各自不超過上限）、兩檔皆為 canonical bytes、schema 與固定欄位、policy 版本與 pin、37 個 GET 的 URL 與順序／status 200／完整 EOF／identity 編碼／時間順序／receipt SHA-256 重算、`data.json` 的 SHA-256 與 bytes 和 `data_version`，以及保存狀態的內部一致性（日曆為遞增平日且含 2026-10-06、`supported` 與因子／理由一致、`supported_from` 與 spread 狀態可由保存的事件與核對結果重算）。任一不符整體拒絕，不修補、不補值。

回傳的 `SavedCalendarActions` 提供 `trading_days`、`events`、`read_day`；每個讀取都要明示 market、security_type、data_version、purpose（`read_day` 另有 symbol、`on_date`、`basis`）。`read_day` 只回因子與事件，不回價格：`raw` 的因子為空，`adjusted` 的因子是該日之後事件因子之積。拒用碼：

- 範圍：`unsupported_market`、`unsupported_security_type`、`unsupported_purpose`、`data_version_mismatch`、`unsupported_symbol`、`unsupported_basis`。
- 檔：`symbol_refused`（該檔 `refused`，連事件也不外露，附第一個理由）。
- 日期：`date_invalid`、`date_outside_window`、`date_not_in_observed_calendar`、`day_incomparable`（附理由）。
- 因子：`adjusted_unsupported`（日期早於 `supported_from` 或該檔 adjusted 整檔拒用，附第一個理由，沒有理由時為 `event_unsupported`）。

載入失敗碼如 `saved_missing`、`saved_reparse_point`、`saved_entries`、`saved_size_cap`、`saved_not_canonical`、`saved_value`、`saved_pin_or_scope`、`saved_get`、`saved_get_receipt_sha`，同樣整體拒絕。

### #98 取得結果與 SPENT 帳

| 項目 | qa1（v1） | v2/qa1 |
| --- | --- | --- |
| namespace／policy | `issue98-tpex-seven-calendar-actions-v1/qa1`／v1（44 GET） | `issue98-tpex-seven-calendar-actions-v2/qa1`／v2（37 GET） |
| seal | 全局 [6149304499](https://github.com/YiCheng0608/stock-lab/issues/98#issuecomment-6149304499) | 全局 [6171379303](https://github.com/YiCheng0608/stock-lab/issues/98#issuecomment-6171379303)；使用者預先同意一次取得 [#1 留言 6171027510](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-6171027510) |
| 結果 | 第 37 個 GET（`TaiwanStockParValueChange`、`data_id=3105`，v1 的第一個面額變更查詢）收到非 200 回應，狀態碼未記錄；批次依設計停止，沒有保存任何資料 | exit 0，37 個 GET 全部 HTTP 200（無 token、0 轉址、0 重試）；獨立 oracle 與產品逐項相等；保存 1 個 bundle，另一個程序讀回 `ok` |
| 收據 | [6159336980](https://github.com/YiCheng0608/stock-lab/issues/98#issuecomment-6159336980) | [6171662145](https://github.com/YiCheng0608/stock-lab/issues/98#issuecomment-6171662145) |
| 額度 | **SPENT／NO-RETRY** | **SPENT 1/1／NO-RETRY** |

額度已用盡，不 restart、replay、clone、hydrate 或另開來源；再取需新的明示使用者授權、新 namespace 與新 seal（見 [FinMind 來源共同規則](#finmind-來源共同規則)）。

v2/qa1 的真實回應觀察（只列計數、日期、類別、狀態；一次觀測，不是 FinMind 對形狀的承諾）：

- **保存的資料版本**：`data.json` 的 SHA-256 `3f0341bedf9082f47caaccb99367e2800488e2c32692133138e85301bcbc3f1d`，即 `data_version` ＝ `tpex-calendar-actions-data/v1:3f0341bedf9082f47caaccb99367e2800488e2c32692133138e85301bcbc3f1d`。讀回時錯市場、錯用途、錯版本各被拒（`unsupported_market`、`unsupported_purpose`、`data_version_mismatch`）。
- **日曆與日狀態**：70 個交易日（2026-07-01～2026-10-12）；七檔價格皆 70 列，`incomparable` 日皆為 0；七檔 `status` 皆為 `usable`，raw 皆可讀。七檔的 spread 檢查皆 `consistent`（每檔 69 個可檢日），語意示範成立（證據為下列 6 個除息日）。
- **F9**：七檔的 `type` 皆為 `tpex`，`date` 為 ISO 格式。
- **事件**：F3 共 6 件除息（3293、5274、5347、6488、6510、8069 各 1，3105 無）；F5、F6a 七檔皆回空陣列；面額變更偵測路徑沒有被真實資料觸發（七檔未解釋日皆為 0）。
- **F3 內部互核**：6 件除息全部通過（差距遠小於一個 tick）；其中 5274 的除息含股票股利（[6171662145](https://github.com/YiCheng0608/stock-lab/issues/98#issuecomment-6171662145) 的標示）。
- **adjusted 可讀範圍**：

| 標的 | 事件（除息日） | 因子狀態 | adjusted 可讀起日 |
| --- | --- | --- | --- |
| 3105 | 無 | — | 2026-07-01 |
| 8069 | 2026-07-20 | supported | 2026-07-01 |
| 3293 | 2026-07-08 | unsupported（`factor_reference_mismatch`） | 2026-07-08 |
| 5274 | 2026-07-07 | unsupported（`factor_reference_mismatch`） | 2026-07-07 |
| 5347 | 2026-07-06 | unsupported（`factor_reference_mismatch`） | 2026-07-06 |
| 6488 | 2026-07-16 | unsupported（`factor_reference_mismatch`） | 2026-07-16 |
| 6510 | 2026-07-09 | unsupported（`factor_reference_mismatch`） | 2026-07-09 |

五件被拒用的除息都是 spread 互核未過：以 `close − spread` 推回的參考價與 F3 參考價相差約 6～75 個 tick（門檻為嚴格小於 1 個 tick）；只有 8069 通過。拒用是 fail-closed 的預期行為，與規格一致，不會錯放行；全局裁定採現狀（[6171697768](https://github.com/YiCheng0608/stock-lab/issues/98#issuecomment-6171697768)），任務統籌的分析見 [6171686376](https://github.com/YiCheng0608/stock-lab/issues/98#issuecomment-6171686376)。對 #38 兩個截止日（last60 窗口起點見 [§49.3](#493-原件驗證與-last60summary-計算) 的已觀測邊界）的影響是任務統籌依上表推算，不是 run 的輸出：adjusted 可用 6 檔，6488 不可用（其 `supported_from` 晚於兩個窗口的起點）。

### #98 未驗與限制

- **spread 除息互核在真實資料上只有 1/6 成立**：原因未知（可能是 `spread` 在 TPEx 除息日的定義與假設不同，也可能是其他原因）。原始 body 依設計不保存，要查原因只能重新取得 `TaiwanStockPrice`，這需要新 seal 與使用者新授權。放寬這條規則（例如 F3 互核通過時 spread 只作參考、不作 gate）屬規格變更，需新 candidate、重驗與新取得；候選記錄見全局裁定 [6171697768](https://github.com/YiCheng0608/stock-lab/issues/98#issuecomment-6171697768)。
- **七檔中 adjusted 全區間可用的只有 3105、8069**：其餘五檔只自上表的可讀起日起可用；七檔承諾不縮（D4），但可用範圍以保存資料為準。
- **期間內沒有真實樣本，只有合成邊界案例**：減資、分割（F5、F6a 回空陣列，其欄位形態仍未驗）、停復牌（`incomparable` 日為 0）、面額變更（偵測路徑未觸發）、paid subscription 與同日多事件。這是資料限制，記為「未驗（期間內不存在）」，不證這些路徑在真實資料上的行為。
- **單一來源、非 PIT**：只用 FinMind，沒有第二來源的對照；7 月與 2026-10-06 之後的日曆日期沒有獨立來源，8～10 月至 2026-10-06 才有 formal 45 日對照。發布時間、首次可得、修訂歷史都是 `unknown`，取得值是「API 當下值」，之後可能被更正；一次成功不證匿名額度、限流、條款或長期穩定。
- **推論**：停牌只有間接證據；`spread` 語意、股票股利面額 10 元、參考價捨入（容差嚴格小於一個 tick）都是明示推論，不是 FinMind 宣告；`TaiwanStockPriceAdj` 不使用，adjusted 是本地由事件因子導出，不是 provider 還原價。
- **面額變更**：不取得、不計因子，只能被偵測為未解釋差異後拒用 adjusted。
- **防護性質**：閘門、audit hook 與 deadline 是進程內協作式防護，不是沙箱；租約 expiry、gzip／br、401／402／403 的真實路徑未觸發，只有合成證據。
- **範圍**：只對這七檔、期間 2026-07-01～2026-10-12 與本地私人衍生用途有效；其他標的、市場、日期、raw body 保存、再散布、Signal、Plan、交易與歷史模擬均不支援。
- **版本**：本節描述 candidate `33db5803f320ac465b21b2f6f0eed55d4e43cebf` 取得時的契約與 v2/qa1 結果；其後程式、policy 或驗收語意變動須重驗並更新本節。本節不宣稱解除 #38 或 #13 的整體 AC；依賴是否解除由全局依整合版本判定。

## 53. #37：七股所涉群組兩截止推論 membership 與 RAM lookup（issue37-industry-membership-inferred-cutoffs-1005-1006-v1）

#37 以四個固定 GET 在取得日 D 一次取得官方上市（櫃）公司基本資料與 FinMind 的證券資訊、下市表，於 RAM 推論 2026-10-05、2026-10-06 兩個截止日 `Semiconductor`、`Optoelectronics`、`Cultural Innovation` 三個必要 official_industry 群組的完整成員集合，供 `industry-membership-inferred-cutoffs-lookup-v1` lookup。本節交付的能力是推論 membership 的取得、獨立驗證與拒用，不保證任何群組有可用成員集合（見[未驗與限制](#37-未驗與限制)）。結果是 non-PIT 的推論，不是歷史真值；分類語意與逐條推論規則見[產業 §6.4](INDUSTRY_CLASSIFICATION.md#64-37-推論集合-consumer-例外)，本節只管理來源、policy、傳輸、授權與限制。產品 `backend/app/industry_membership_inferred_source.py`，測試 `backend/tests/test_industry_membership_inferred_source.py`。本節不提升也不改寫其他節的 policy、pins、capture 或 default，也不含任何取回的列、原始 body 或成員清單。標題中的 `v1` 是本節識別字，不是 policy 版本。

### #37 版本、外部 pins 與上限

| 項目 | 內容 |
| --- | --- |
| 外部 policy | version `issue37-industry-membership-inferred-cutoffs-1005-1006-v2.1`，schema `issue37-industry-membership-source-policy/v1`（鍵集合不變，v2 只改文字值）；canonical UTF-8（sorted keys、compact JSON、無尾 LF）。位元組數 15,152 與 SHA-256 `f6df04241f97fd50948b54d463cf829526b6f12c3b259c642e2c0d20d6b51676`（[全局發布 v2.1](https://github.com/YiCheng0608/stock-lab/issues/37#issuecomment-6174861923)）釘在產品常數 `POLICY_BYTES`／`POLICY_SHA256`；未設定、SHA-256 或位元組數不符一律拒用（`policy_pin_unset`、`policy_pin`、`policy_canonical_mismatch`）；產品不能由被測 policy 自建 expected。傳輸欄與 [§49](#49-32-qa1qa2七股-finmind-nominal-ohlcv-日線-last60-與兩截止-raw-算術issue32-seven-nominal-ohlcv-two-cutoffs-v1) 的 #32 v3 policy 相同處逐字相同，差異只有 3 個 host、4 個固定 URL、無 query 的官方請求、官方 content-type 與 BOM、body／raw／roots 上限、namespace 與 UA |
| namespace／UA | `issue37-industry-membership-inferred-cutoffs-1005-1006-v2/qa2`（policy version 的 `.1` 不改 namespace）；`stock-lab-issue37-local-ram/1` |
| profile／用途 | profile `free_public_local`；source_use `local_personal_noncommercial_process_ram_inferred_cutoff_membership_snapshot`；consumer `industry-membership-inferred-cutoffs-lookup-v1`；market TW/TWSE+TPEx、instrument_type `ordinary_stock`；storage `process_RAM`，`artifact_bytes` 0 |
| 截止與取得日 | cutoff 2026-10-05、2026-10-06；D 是第一個 GET 開始時的 Asia/Taipei 日期，須在 2026-10-06～2026-10-31，四個 capture 須在同一日完成，距台北午夜不足 210 秒不開始；日期不符在第一個 GET 之前拒用，不花用額度 |
| 請求 | 固定 4 個 GET，順序固定，第一次失敗即停（未嘗試者不算 SPENT）：(0) `https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInfo`（body ≤4 MiB）；(1) `https://openapi.twse.com.tw/v1/opendata/t187ap03_L`（≤4 MiB）；(2) `https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O`（≤4 MiB）；(3) `https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockDelisting`（≤2 MiB）。FinMind 只帶 `dataset`，官方不帶 query；Delisting 不送日期參數，在 RAM 篩 `[C, D]`；host 只有 `api.finmindtrade.com`、`openapi.twse.com.tw`、`www.tpex.org.tw`。不換 dataset、路由、日期或 host 再試 |
| 上限 | `max_gets` 4、每來源 1；raw 合計 12 MiB；retained roots 估計 48 MiB（不是 RSS 或 peak）；單一請求 20 秒、整批 180 秒（皆 cooperative，非 OS hard deadline）；redirect 0、retry 0、token／cookie／proxy 0；401／402／403 為 `http_auth_or_payment_stop`，是第一次失敗 |
| 真實執行閘門 | 預設 transport 須有 `FinancialStart`（version `issue37-financial-start-v1`、namespace、policy pin）與一致的 `ExecutionBinding`（獨立 top-level QA、`xhigh`、candidate 與程式 hash），seal 留言須在 #37 且編號大於 6174861923（policy v2.1 發布留言，已用掉的 qa1 seal 與更早的位置都不能再當 seal），並使用預設時鐘；一次性 ledger 在進程內不重置。授權本身不是 seal |

### #37 用途、授權與署名

用途只限免費公開、個人非商用、本地盤後研究與 RAM 取得／驗證／consumer。Policy `supported_use`：`local_personal_noncommercial`、`process_ram_snapshot`、`industry_membership_inferred_cutoff_lookup`；`unsupported` 19 項：`historical_pit`、`publication_time`、`first_availability`、`revision_history`、`classification_effective_date`、`off_cycle_reclassification_exclusion`、`other_cutoffs`、`theme_membership`、`hot_group_v1_score`、`group_return`、`actionable_strategy`、`plan`、`trading`、`historical_simulation`、`raw_disk_storage`、`db_write`、`redistribution`、`mirror`、`deployment`。產品只接受預設 purpose，其餘一律 `unsupported_purpose`。FinMind 是服務提供者，不是官方直接來源；TWSE、TPEx 資料依[政府資料開放授權條款第 1 版](https://data.gov.tw/license)，用途限本地 RAM，不再散布原件。以下三段署名與 policy `rights` 逐字相同：

> FinMind（266 UTF-8 bytes）：FinMind: TaiwanStockInfo, TaiwanStockDelisting; local personal noncommercial RAM snapshot only; no raw redistribution/mirror. FinMind is the service provider; this is not an official direct feed and the Chinese industry-name to code mapping is an explicit inference.

> TWSE（605 UTF-8 bytes）：臺灣證券交易所（Taiwan Stock Exchange, TWSE）[2026] 上市公司基本資料（dataset18419；openapi.twse.com.tw/v1/opendata/t187ap03_L；issue37-industry-membership-inferred-cutoffs-1005-1006-v2.1）。此開放資料依政府資料開放授權條款（Open Government Data License）進行公眾釋出，使用者於遵守本條款各項規定之前提下，得利用之。政府資料開放授權條款－第1版：https://data.gov.tw/license。原欄、來源及完整性保留；用途限本地 RAM，不再散布原件；2026-10-05與2026-10-06各群組成員為本地推論衍生結果。

> TPEx（629 UTF-8 bytes）：財團法人中華民國證券櫃檯買賣中心（Taipei Exchange, TPEx）[2026] 上櫃公司基本資料（dataset25036；www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O；issue37-industry-membership-inferred-cutoffs-1005-1006-v2.1）。此開放資料依政府資料開放授權條款（Open Government Data License）進行公眾釋出，使用者於遵守本條款各項規定之前提下，得利用之。政府資料開放授權條款－第1版：https://data.gov.tw/license。原欄、來源及完整性保留；用途限本地 RAM，不再散布原件；2026-10-05與2026-10-06各群組成員為本地推論衍生結果。

署名中的機關名稱與 dataset 編號取自本 repo 既有引用（[§42](#42-m1-twse-issuer-industry-trace-20261008-1b1兩碼引用與同截止原件)的 dataset18419、TPEx 公司基本資料的 data.gov.tw 編號 25036），未向 data.gov.tw 重新核對提供機關欄位。

### #37 原件驗證與推論邊界

- **傳輸**：沿用 [§49.3](#493-原件驗證與-last60summary-計算)的取得與標頭規則：只收 HTTP 200；`content-encoding` 須 identity 或無；framing 接受 content-length、chunked、close-delimited，content-length 與 chunked 並存拒，達上限仍無 EOF 拒；四個身分標頭（`content-length`、`content-encoding`、`transfer-encoding`、`content-type`）重複即拒，其他標頭重複忽略；`set-cookie` 不送出、不使用、不保存。兩個 FinMind GET 的 `content-type` 仍須是 `application/json`（可接 `; charset=utf-8`），body 為 strict UTF-8 且無 BOM。兩個官方 GET 的 `content-type` 只記錄原值、不 gate；body 一律須是 strict UTF-8（可去掉一個開頭 BOM，記 `bom_present`，body SHA-256 仍對原 bytes）的 JSON array 並通過逐欄 schema，任何解析失敗就是第一次失敗。這是以 body 的嚴格解析取代未驗的 header，避免類似 [§47](#47-36-qa1qa2七股-tpex-法人六日-dated-csv-與兩截止五日分子issue36-two-cutoffs-v1)／#31 qa2 `application/csv` 的額度浪費。
- **採用欄**（其餘欄位忽略；只有結構性錯誤整批拒用，欄位值的任何異常都是 unknown，只會拒用受影響的群組或截止日，推論規則見[產業 §6.4](INDUSTRY_CLASSIFICATION.md#64-37-推論集合-consumer-例外)）：

| 來源 | 採用欄 | 規則 |
| --- | --- | --- |
| FinMind `TaiwanStockInfo` | `date`、`industry_category`、`stock_id`、`stock_name`、`type` | 外層恰為 `status`（整數 200）、`msg`（`success`）、`data`；`date` 只有 `YYYY-MM-DD` 真實日期且不晚於 D 才算有日期，其餘（型別錯、空、null 類字串、含時間、非真實日期、晚於 D）日期 unknown；`stock_id` 非空且 ≤32 字元才可用；`type` 只有 `twse`、`tpex` 參與比對，不可用的 `type` 是交易所 unknown |
| TWSE `t187ap03_L` | `出表日期`、`公司代號`、`產業別`、`上市日期` | 出表日期 7 位民國真實日期才可用，feed 出表日是可用列的唯一值；代號 4～6 位大寫英數才可用，四位數字重複者不計成員；產業別以 §3 mapper 精確對應 |
| TPEx `mopsfin_t187ap03_O` | `Date`、`SecuritiesCompanyCode`、`SecuritiesIndustryCode`、`DateOfListing` | 同上 |
| FinMind `TaiwanStockDelisting` | `date`、`stock_id`、`stock_name` | 外層同 `TaiwanStockInfo`；`date` 為 `YYYY-MM-DD` 真實日期（晚於 D 仍是已知日期），其餘 unknown |

  上市日四種格式依字元長度與分隔符互斥判定，且都必須是真實日期：8 位數字是西元 `yyyyMMdd`（`gregorian8`）、7 位數字是民國 `yyyMMdd`（`roc7`）、6 位數字是民國 `yyMMdd`（`roc6`）、`Y/M/D` 限 4 位西元年且只用 `/`、月日 1～2 位（`ymd_slash`）。不 trim、補零或猜測；其餘（3 位民國年加分隔符、`-` 分隔、null、缺漏、非真實日期如非閏年的 2 月 29 日）一律 `unknown`，拒用該檔所屬群組，不是整批失敗。`inspection()` 的 `listing_date_formats` 依交易所各記這五種的列數（`unknown` 含 null 與缺漏），同一交易所五項總和等於該交易所列數，供 QA 核對實際出現的格式；普查（見下）把 `unknown` 再細分為 `invalid_calendar`、`missing`、`json_null`、`non_string`、`empty`、`blank`、`null_text`、`other_string`，八項之和等於 `unknown`。
- **身分邊界**：三類互不重疊。（1）ordinary：剛好四個 ASCII 數字。（2）可用的非 ordinary：FinMind `stock_id` 為 1～32 字元的其他字串、官方代號符合 `[0-9A-Z]{4,6}` 但不是四位數字（如 `2330A`、`00631L`、`23301`、`23A0`）；官方端與 FinMind `TaiwanStockInfo` 端的這類列一律排除於集合、delisting 與轉板判定之外，不產生任何拒用理由，`TaiwanStockDelisting` 的非四位代號同樣忽略。（3）不可用：非字串、null、缺漏、空、全空白、`none`／`null`／`nan`／`nat`／`na`／`n/a`／`undefined`（不分大小寫、不 trim）、FinMind `stock_id` 超過 32 字元、官方代號不符 `[0-9A-Z]{4,6}`；該列無法歸屬某檔，不進任何集合，只拒用它能到達的群組或截止日（`info_identity_unusable`、`official_identity_unusable`、`delisted_identity_unusable`）。`inspection()` 的 `excluded_non_ordinary` 只回報第（2）類被排除的列數：`official.TWSE`、`official.TPEx`，以及 `finmind.TWSE`、`finmind.TPEx`（`TaiwanStockInfo` 的 `type` 為 `twse`、`tpex`）與 `finmind.other`（其他 `type`）；不記任何原始代號字串。
- **整批拒用**：取得日超出範圍、四個 capture 跨台北日、外層形狀或列數不符、任一列不是 JSON object（`row_not_object`）、官方 feed 沒有可用出表日（`official_report_date`）、可用出表日不唯一（`official_report_date_not_uniform`）或不在範圍（`official_report_date_out_of_range`）、七股任一檔在官方 snapshot 不屬三個必要群組（必要群組假設錯誤；出表日不可用的列仍算涵蓋；同一 feed 內重複的代號須每一列都在必要群組才算涵蓋，與列的順序無關，收據描述其中不涵蓋者以 `industry` 字串最小的一列；同一 symbol 兩個官方 feed 都有時以 TPEx feed 的列為準）。出表日與七股檢查在前三個 GET 解析後即做，失敗時後面的 GET 不執行。七股檢查先掃完七檔再拒用，診斷逐檔記錄未涵蓋的股票：`uncovered_count`（1～7），以及每檔的 `uncovered_<n>_symbol_index`（0～6，對應七股順序）、`_exchange`（`TWSE`、`TPEx` 或 `absent`；同一 symbol 兩個官方 feed 都有時以 TPEx 列為準）、`_code`（官方原始產業 code：1～4 位 ASCII 英數原樣記錄，null、缺漏或空字串記 `<null>`，其餘字串記 `<unrepresentable>`，原始字串不寫入）、`_group`（mapper 的 canonical 群組或 `unknown`）。必要群組綁在 policy 與 seal，執行時不改範圍；實值不符時本次拒用並回報實值，改群組須另訂 policy 並重發 seal。已不存在的整批拒用碼（改為值層級 unknown）：`info_row_schema`、`info_date`、`info_date_after_acquisition`、`info_stock_id`、`delisting_row_schema`、`delisting_date`、`delisting_stock_id`、`official_row_schema`、`official_symbol`、`official_duplicate_symbol`（同名碼改為群組層級理由）、`row_schema_type`，以及 JSON 裸 `NaN`／`Infinity` 的 `nonfinite_json_number`（來源 body 中視為非字串值；物件重複 key 仍是 `duplicate_json_key`）。新增的群組或截止日層級理由碼見[產業 §6.4](INDUSTRY_CLASSIFICATION.md#64-37-推論集合-consumer-例外)：`finmind_latest_date_unresolved`、`info_identity_unusable`、`info_type_unusable`、`delisting_date_unknown`、`delisted_identity_unusable`、`board_transfer_evidence_date_unknown`、`board_transfer_listing_date_unknown`、`board_transfer_type_unknown`、`official_identity_unusable`、`official_duplicate_symbol`、`official_row_report_date_unknown`；它們只出現在各群組的 `reasons`，`admit_independent_verification` 只比對狀態與成員。
- **形態普查與診斷計數**：每個來源先對每個 object 列的識別欄與日期欄（Info 另含 `type`、`industry_category`；官方另含產業別、上市日）依互斥類別各記一個計數，再做任何驗證與判定，所以第一個失敗之後的列也已計入。`inspection()["census"][來源][欄位][類別]` 只有整數（無任何原始字串），來源為 `info`、`twse`、`tpex`、`delisting`（已完成計數的來源才有），另有每個來源的 `rows` 與 `rows_not_object`；各欄位的類別之和等於 `rows − rows_not_object`，成功時 `rows` 等於 `row_counts` 對應項。類別（依序判定、取第一個符合者）：日期（Info、Delisting `date`）13 類 `missing`、`json_null`、`non_string`、`empty`、`blank`、`null_text`、`iso_valid`（真實日期且不晚於 D）、`iso_future`、`iso_invalid_calendar`、`iso_with_time`、`digits8`、`slash_date`、`other_string`；官方出表日 11 類（日期六個前綴類加 `roc7_valid`、`roc7_invalid_calendar`、`digits8`、`iso_shape`、`other_string`）；官方上市日 12 類（四種可用格式加 `invalid_calendar` 與上述不可用類）；FinMind `stock_id` 12 類（不可用七類 `missing`、`json_null`、`non_string`、`empty`、`blank`、`null_text`、`oversize`，加 `ordinary`、`digits_other_length`、`alnum_mixed`、`other_ascii`、`non_ascii`）；官方代號 9 類（不可用六類加 `ordinary`、`grammar_non_ordinary`、`bad_grammar`）；Info `type` 9 類（`twse`、`tpex`、`other_string` 加不可用六類）；Info `industry_category` 9 類（`required_name`、`other_name`、`unknown_name` 加不可用六類）；官方產業別 10 類（`required_group`、`other_group`、`unmapped_two_digit`、`other_string` 加不可用六類）。整批拒用時，已完成普查的所有來源的計數也以 `census_<來源>_<欄位>_<類別>`（及 `census_<來源>_rows`、`census_<來源>_rows_not_object`）整數鍵寫入失敗診斷，共 160 個固定鍵，名稱與 0～200,000 的整數範圍都經白名單驗證，其餘一律丟棄。`inspection()["stock_resolution"]` 以計數回報 ordinary `stock_id` 的最新列判定：`single_row`、`same_value`、`newest_unique`、`newest_tied`、`date_unresolved_related`、`date_unresolved_unrelated`，合計等於 ordinary 的相異 `stock_id` 數。推論完成後（pending 與 available）`inspection()["d_set_difference"][C][群組]` 回報 `official_only`（官方有、FinMind 集合沒有）、`finmind_only_explained`（被 `[C, D]` 內下市列解釋）、`finmind_only_unexplained` 三個整數，不記代號；`official_only` 與 `finmind_only_unexplained` 任一大於 0 即該群組有 `cross_source_mismatch`。只讀、不改判定。普查、`stock_resolution` 與 `d_set_difference` 只描述這次取得的形態與規模，不證任何欄位格式是來源的正式契約。
- **獨立 oracle**：`acquire` 後 snapshot 為 pending；獨立 QA 從 `inspection()` 的原 bytes 重建 2 截止日 × 3 群組各自的狀態（`members` 或 `rejected`）與成員，連同四份 receipt 雜湊、D、兩份出表日與四個來源列數交給 `admit_independent_verification`；任一不符即終止該 snapshot，不能再試另一份主張。pending、failed、expired、released 都不能 lookup。
- **lookup 與拒用**：只接受兩個截止日、三個必要群組與 official_industry namespace；錯日、非必要群組、題材 namespace、被拒用的群組、digest 或 policy 不符、release 與 expiry 之後皆拒用。每個接受的結果帶 `inferred_from_post_cutoff_snapshot`、`effective_from`／`effective_to`（`unknown`）、`pit`（false）、殘餘風險代碼、D、兩份官方出表日、四個來源 digest（各 receipt 的 `request_started_utc` 是請求開始、`observed_utc` 是 body 讀完，為兩個獨立 UTC 欄位，對應 AC-1 的「取得」與「observed」時間），以及 `finmind_only_delisted_member`、`board_transfer_old_tpex_identity` 等逐檔旗標；被拒用的群組只回 `group_rejected` 與理由碼，不回成員與這些欄位（見[產業 §6.4](INDUSTRY_CLASSIFICATION.md#64-37-推論集合-consumer-例外)）。

### #37 未驗與限制

- **契約假設**：解析器依下列假設設計；外層形狀與 header 不符整批拒用，欄位值的形態不符則該值 unknown，不放寬、不猜測：四個來源的實際回應 header 與欄位、TWSE／TPEx 實際回應的欄位與日期格式（TPEx 的 `Date`、`SecuritiesCompanyCode`、`SecuritiesIndustryCode`、`DateOfListing` 只有 Swagger 宣告為依據，宣告不證實際回應；`Date` 另見 [產業 §1](INDUSTRY_CLASSIFICATION.md#1-官方證據-snapshot)）、FinMind 對創新板與 KY 的 `industry_category` 命名是否與 §2 市場名稱相同、`TaiwanStockInfo` 是否保留已下市標的、是否對同一 `stock_id` 同日只有一列（多列且值不同時拒用，不選一列，見[產業 §6.4](INDUSTRY_CLASSIFICATION.md#64-37-推論集合-consumer-例外)）、`TaiwanStockDelisting` 是否含非上市櫃項目。這些假設若不成立，會使對應群組或整個截止日不能通過，結果與普查計數照實回報。
- **非 PIT**：群組成員是以取得日 D 的 snapshot 推論；分類生效、失效、發布與修訂時間皆 `unknown`。FinMind `TaiwanStockInfo.date` 是更新日期，不是生效日；`TaiwanStockDelisting.date` 的語意（最後交易日或下市生效日）未定，`date==C` 一律拒用該群組。
- **年度外調整**：TWSE 要點第二點與第三點第四項允許年度以外調整，`[C, D]` 內的臨時調整無法排除，以 `off_cycle_reclassification_not_excluded` 隨每個結果回傳。
- **範圍**：只對兩個截止日、三個必要群組、官方產業 namespace 與本地 RAM 有效；不證歷史分類、群組報酬、排名、題材歸屬、保存、時間接線或策略。本節不解除母單 #21 對可用群組成員集合的依賴，也不解除其整體 AC。
- **接受路徑**：以 policy v2.1 驗證的真實取得只證明取得、獨立比對與 fail-closed 拒用的路徑；接受結果的成員集合與接受欄位只有合成資料證據，沒有任何真實資料下的接受結果，所以正向 lookup（取得可用成員集合）尚未成立，是本能力的剩餘缺口。
- **防護性質**：閘門、audit hook 與 trace 是進程內協作式防護，不是沙箱；retained estimate 不是 RSS 或 peak，生命週期驗收不代表實體抹除；一次性 ledger 只在進程內有效，外部 seal 才是權威。
