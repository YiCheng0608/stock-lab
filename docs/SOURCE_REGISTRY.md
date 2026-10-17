# Source registry、用途 gate 與官方來源契約

本文負責官方來源 identity、授權、用途 gate、capture 與 consumer 契約。各節有限 review 不代表其餘來源已重新查證、全市場 coverage 或 PIT。

本文件是免費公開官方來源的 identity、授權、用途 decision、runtime capture 與已接 consumer 的權威。第 3 節是原 snapshot 四來源，第 8 節是另需 explicit 單來源 manifest 的 TPEx 單日法人；不能將新增來源當成 bundled default 或沿用舊 registry version。一次 HTTP 200、來源名稱或資料日期都不能補成完整 coverage、發布時間、first availability、revision lineage 或 historical PIT。

## 來源選用原則（FinMind 為主）

新的取得方案、恢復的暫停單與新來源准入，先以 FinMind（`https://api.finmindtrade.com/api/v4/data`）為主要來源；FinMind 沒有該資料集或無法滿足用途時，才另提其他來源，並在原 Issue 記理由。只用 FinMind 時，官方 anchor 改為 FinMind 內部一致性核對，單位與 scale 寫成明示推論並列入該來源節的限制；需要其他來源（含官方核對）時另提方案。

用途限免費、本地個人非商用研究；署名、不 mirror、不再散布 raw 等權利界線見下節 [FinMind 來源共同規則](#finmind-來源共同規則)。FinMind 要求付費、登入，或回 401／402／403 即停止，不在同一額度內重試；改用其他來源須依上段另提方案。本原則是來源方向，不是取源授權：每次真實取得仍須具體範圍（URL、次數、caps），依 [§1](#1-registry-與-policy-契約) 的版本化 policy 與 pin，並有單一 namespace 與核發前經使用者確認的 seal（見下節）；已 SPENT／NO-RETRY 的額度不因本原則恢復。

### FinMind 來源共同規則

本節是「外部 policy＋namespace＋seal」RAM 取得 namespace 的共同規則；各來源節只保留版本字串、pins、本節特有上限與差異。

- **用途**：只限免費公開、本地個人非商用、盤後研究與 process RAM 取得／驗證／consumer；不落盤、不發布 raw、不鏡像、不再散布、不部署、不交易。`historical_pit` 不支援，publication／first availability／revision 固定 `unknown`；其他 cutoff、代號、dataset 與用途在取數前拒用，不外推。FinMind 是服務提供者，不是官方直接來源；只用 FinMind 時沒有官方 anchor，單位與 scale 是明示的 provider 推論，比對只是同一份 bytes 的內部一致性。免費使用是文件推論（`token` 選填），FinMind 回 401、402、403 或任何要求付費、登入的回應即首敗。
- **額度與 seal**：每個 namespace（`…/qaN`）是獨立的一次額度；新授權不是恢復前一個，前一個的 SPENT／NO-RETRY 照舊並登錄於[治理 #1](https://github.com/YiCheng0608/stock-lab/issues/1)。使用者授權本身不是 seal：每次 real run 另須全局核發 fresh financial-start seal（綁定 policy SHA-256、namespace、唯一 URL 清單、candidate、產品／測試／script hash、用途、caps 與有效期），由獨立 QA 執行一次；產品不能由被測 policy 自建 expected pin，policy、seal 或 execution binding 不符在 GET 之前拒絕、不花額度。每 URL 最多 1 次、首敗即停且 attempted 即 SPENT；redirect 0、retry 0、token／cookie／proxy 0、identity encoding；原件只在 RAM，結束後 release 並撤銷 handle。再取需新的明示授權、新 namespace 與新 seal；不 restart、replay、clone 或 hydrate 已釋放的原件。
- **防護性質**：閘門、audit hook 與 trace 是進程內協作式防護，不是沙箱，僅 Windows；每 URL／整批 timeout 為 cooperative 檢查，不是 OS 硬 deadline；retained-roots estimate 是 deduplicated `getsizeof` 估算，不是 RSS 或 peak；生命週期驗收不代表實體抹除。
- **署名**：署名方式依各版本 policy 宣告，並隨 policy SHA-256 被 seal 綁定。權利是否充分是使用者決策，QA 只核對它被 seal 綁定。

## 現行節次索引

各版本 policy、pins 與 capture 彼此獨立；新 explicit 版本不提升舊 default、不沿用舊 capture bytes，也不作 implicit latest。

| 節 | 範圍 | 現況 |
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
| [§39](#39-2026-10-08歷史收盤新候選審查與官方事件重選) | 歷史收盤新候選審查與官方事件重選（39.1 M2-OFFICIAL-EVENT-DATE-RANGE-20261008-1 實際來源結果） | 現行 |
| [§40](#40-m2-official-event-kind-20261008-1b1事件類型實際來源與有限接受) | M2-OFFICIAL-EVENT-KIND-20261008-1/B1：事件類型實際來源 | 現行 |
| [§41](#41-m1-twse-issuer-event-profile-20261008-1b1真-issuer-與同截止事件有限接受) | M1-TWSE-ISSUER-EVENT-PROFILE-20261008-1/B1：真 issuer 與同截止事件 | 現行 |
| [§42](#42-m1-twse-issuer-industry-trace-20261008-1b1兩碼引用與同截止原件) | M1-TWSE-ISSUER-INDUSTRY-TRACE-20261008-1/B1：兩碼引用與同截止原件 | 現行 |

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
- 資料集適用 [OGL 1.0](https://data.gov.tw/license) 及 [TPEx 網站條款](https://www.tpex.org.tw/zh-tw/gtsm_disclaimer.html?l=zh-tw)第 7 點的開放資料例外；條款第 5 點限定經同意方式自動下載的限制保留，不因 endpoint 可讀而消失。

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

## 39. 2026-10-08：歷史收盤新候選審查與官方事件重選

本次新FinMind primary核對提供 [TaiwanStockPrice technical API線索](https://finmind.github.io/tutor/TaiwanMarket/Technical/)，與舊Sponsor broker候選分開。[2026-07-13使用條款](https://finmindtrade.com/analysis/#/Sponsor/terms_of_use)與[2026-07-12 disclaimer／licenses](https://finmindtrade.com/analysis/#/Sponsor/disclaimer)依方案界定API／SDK服務用途；服務不包含對外再散布／轉售／鏡像，對外公開仍須自行確認原資料機關授權要求。這些證據當時尚未建立exact普通股歷史source owner／rights／各用途與獨立calendar／consumer pins；MIT軟體license或一般公開管道聲明不代data permission。本節只保留當時的候選審查結論，不構成全域禁止。

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
