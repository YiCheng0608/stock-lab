# Source registry、用途 gate 與官方來源契約

更新：2026-10-07。本文負責官方來源 identity、授權、用途 gate、capture 與 consumer 契約。原四來源查證基準為 2026-09-12；TPEx 單日法人另需 explicit 單來源 manifest（§8），TWT48U selected／feed 見 §9／§11。§10／§12 保留原候選缺證；§13 是另以獨立 policy 准入並驗收的 TPEx 兩股多日 CSV／有界日曆及計算。各節有限 review 不代表其餘來源已重新查證、全市場 coverage 或 PIT。

本文件是免費公開官方來源的 identity、授權、用途 decision、runtime capture 與已接 consumer 的權威。第 3 節是原 snapshot 四來源，第 8 節是另需 explicit 單來源 manifest 的 TPEx 單日法人，第 13 節是獨立版本的政府連結 CSV policy；不能將新增來源當成 bundled default 或沿用舊 registry version。一次 HTTP 200、來源名稱或資料日期都不能補成完整 coverage、發布時間、first availability、revision lineage 或 historical PIT。

法人現行explicit10/06兩股5／20日窗口、完整24日曆及新pins見[§31](#31-m1-chips-cutoff-1006-1同1006法人窗口與完整有界日曆)；W8八截止／27日曆與96 net依[§19](#19-m1-w8八截止法人來源與完整有界日曆)原範圍保留，§13–18保留歷史，不作implicit latest。M1-PRICE-1單日價格見[§20](#20-m1-price-1tpex-兩股單日價格來源與准入)。

M2既有10/06七股scope見[§29](#29-m2-focus-stock-scope-5七股來源准入)；新explicit10/07八股／新body及獨立policy見[§35](#35-m2-focus-stock-scope-6八股與新來源日准入)，不提升old defaults或沿用舊capture bytes。§20～34保留已驗歷史版本與金融表；開放平台歷史用途缺口見[§28](#28-m1-history-open-data-link-1開放平台metadata與歷史用途缺口)。獨立私人保存／跨程序讀回見[§30](#30-m1-price-save-1私人單日保存與跨程序讀回)，本批沒有private I/O或chips GET。

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

### 12.3 本輪驗收邊界與下一步

本批只有 metadata／唯讀 source review，程式寫入範圍為空；未取法人 body，未跑 tests／backend／build／UI，不由前輪測試追認准入。入口副作用見[開發文件](development-baseline/README.md)，角色／清理限制見[協作紀錄](TASK_COORDINATION.md)。

取得 §12.2 的 exact 權利與資源證據後，才由統籌核定有界驗證及必要實作。優先順序依 [ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑)，不以此來源等待暫停其他已具依賴的核心能力。

## 13. M1-W1：TPEx 多日法人與完整有界交易日

本節保留 W1 的歷史版本與單截止驗收；現行四截止與新版 policy 見[§15](#15-m1-w4四截止法人來源與全月日曆核對)。

**來源、production consumer 與具名真資料／計算驗收已有限接受。** 支持 TPEx 3105／6488、唯一資料截止2026-10-02，日曆限2026-09-01～10-02。已解除多日原件、完整有界交易日及5／20日淨超計算依賴；後續 W2 同截止 API／UI 操作亦有限接受，見[個股頁 §18](STOCK_RESEARCH_PAGE.md#18-m1-w2同截止法人窗口與原件追溯)，不計完整 M1 或 PIT。

### 13.1 獨立 policy 與四用途

[`tpex_institutional_window.py`](../backend/worker/tpex_institutional_window.py) 使用 `window_policy()`，版本為 `tpex-institutional-window/w1-v1`、profile `free_public_local`。外部 pins 為 `policy_version=m1-w1-tpex-window-2026-10-04.1`、`policy_digest=sha256:5b5129cdc39ab0bac9eac89246917f8721c118e2f9c18ed02234972e6c5dc773`；型別／來源集合、四用途、整份 policy 與外部 digest 必須一致。原 registry／policy JSON、P2a manifest、bundled default 與其 pins 未改。

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

### 13.4 明示記憶體取得與有限接受

只有 `MemoryWindowCache.load(...)` 明示核定 policy／profile／外部 pins 後可取得；`summarize_window_captures(...)`、snapshot／get 與 import 不取網路或寫檔。一次 load 最多22 GET（2 index＋20 daily），daily≤2 MiB、index≤1 MiB、總≤42 MiB，每 request HTTP timeout 15秒、零 retry／redirect、identity encoding；不是整批 hard deadline 或跨程序 rate limiter。日曆失敗時不取後續法人日檔。一次嘗試後不可重新 load；cache 只在 process memory，讀取重驗同 bytes，失敗不 fallback 舊版本。raw_store 用途准入不等於本批准許落盤；未保存原件，不支持磁碟重開或離線重播這次原件。

統籌已用**實際 production consumer**取得22份原件、完整22開市日及兩股40個 selected rows，逐列原序、880個金融原字串與20日 body SHA 對獨立原件相符；12個窗口 net 各由 buy－sell 重算一致，memory guard 磁碟／mutation／未准入網路0，exit 0、零新增檔案。有限參考如下，順序為外資／投信／自營商、單位股：

| 標的 | 5日 | 20日 |
| --- | --- | --- |
| 3105 | `[21655769, 2223800, 1578271]` | `[25496297, 16596388, 1183894]` |
| 6488 | `[-2452286, 920329, 229491]` | `[-13191795, -1012703, 261501]` |

解析／日曆／窗口與 loader 邊界由 [`test_institutional_windows.py`](../backend/tests/test_institutional_windows.py) 重建；synthetic 邊界不代真來源。W2 first POST 是新取得，22 body hash 與 W1 相符但 capture／receipt 不混同。精確命令、版本、UTC、full hashes、首 probe 失敗與修正收據留原 task。尚缺範圍外來源／日曆、更廣歷史／修訂、PIT、研究條件及完整 M1；P2a／P2b 與 §10原 OpenAPI 候選不放寬。

## 14. M1-W3：三截止法人來源與窗口

本節保留 W3歷史版本／三截止觀測；現行四截止與全月核對見[§15](#15-m1-w4四截止法人來源與全月日曆核對)。

**真來源、三截止計算及具名 API／UI 已有限接受。** 範圍為 TPEx 3105／6488、2026-09-30／10-01／10-02，日曆仍限2026-09-01～10-02。W3 實際取得新增9/1、9/2原件並解除三截止依賴；不沿用 W1 的20日請求白名單或舊 pins 放行。產品操作見[個股頁 §19](STOCK_RESEARCH_PAGE.md#19-m1-w3三截止法人窗口與原件追溯)。

### 14.1 新版 policy、來源與有界取得

W3當時 worker 為 `tpex-institutional-window/w3-v1`，profile 仍為 `free_public_local`；外部固定 pins 為 `policy_version=m1-w3-tpex-window-2026-10-04.1`、`policy_digest=sha256:9de27224cc57512f4e38455717eb51f8512eb890667119a5d02444810e0ad4db`。整份 policy／來源集合／用途及 digest 必須一致；scope 明列 `supported_cutoffs` 三日。原 registry／P2a manifest／bundled pins 未變，W1 policy 留作歷史。

| Source ID | W3 來源版本與查詢範圍 |
| --- | --- |
| `tpex_government_institutional_csv` | `dataset-11856-dated-csv-observed-2026-10-04/v2`；沿 §13.1 的 dataset11856 exact GET，`d=115/MM/DD` 僅完整22個 expected sessions，包括新驗9/1、9/2。 |
| `tpex_government_index_csv` | `dataset-11391-month-csv-observed-2026-10-04/v1` 未變；沿 §13.1 exact GET，僅 `date=2026/09/01`／`2026/10/01`。 |

政府開放授權、TPEx 署名與原始成交統計基礎沿 §13.1／13.3；兩來源的 `local_fetch`／`raw_store`／`summarize` 僅此 policy 範圍 admitted，`historical_pit=unsupported`。准入 raw_store 不授權本輪落盤，原件只存 process memory。

一次明示 load 為22 daily＋2 month 的 union，最多24 GET；daily≤2 MiB、index≤1 MiB、整批≤46 MiB（48,234,496 bytes），每 request timeout15秒、identity encoding、零 retry／redirect。日曆失敗不續取 daily；成功或失敗後不重取、refresh 或較早 fallback。import／snapshot／get不取外網、不寫檔或 DB；整批 hard deadline、跨程序 rate limiter及更廣日期不在此契約。

### 14.2 同日曆的三個有界窗口

日曆 `tpex-2026-09-01_2026-10-02-weekdays-11503027221/v1` 與計算 `independent-net-sum/expected-session-inclusive-v1` 均未改。§13.2 的周一至五／兩個明示閉日及兩月正值、唯一 OHLC 集合仍須恰好核足22個 expected sessions，日曆壞則所有窗口拒用。資料取得 union 包含較晚日，所選 cutoff 的窗口只採 `date<=cutoff`，不讓未來原列進入該窗。

| cutoff | 截止內完整 sessions | 5日起點 | 20日起點 |
| --- | ---: | --- | --- |
| 2026-09-30 | 20 | 2026-09-22 | 2026-09-01 |
| 2026-10-01 | 21 | 2026-09-23 | 2026-09-02 |
| 2026-10-02 | 22 | 2026-09-24 | 2026-09-03 |

### 14.3 原件與按窗口拒用

UTF-8、exact 25／6欄 header、全列日期／欄數／唯一代碼／非空名稱，以及 selected 全金融欄位的 canonical int64、七組 buy－sell／組成及 total gate 沿 §13.3，穩定公式與股單位不變。新9/1、9/2 probe 實際各 HTTP200，兩股4 selected rows／88金融原字串已獨立核對；不稱其他標的金融值已驗。

缺 required date、錯日／壞值、selected 缺列、hash／receipt 不合格或競爭 revision，只使需要該日的窗口 unavailable；5日不需該日可維持 available。缺日不補零、縮窗、挑版、採較早或未來替代；policy／日曆壞則全拒用。每窗仍列 required／valid／missing／invalid dates、原因及原列／版本／hash／UTC收據，讀回重驗同一批 immutable bytes。取得時間不代發布或 first availability，下載修訂保障及 lineage仍 unknown，本次事後資料日期統計不是 PIT、Signal、研究條件或磁碟保存。

### 14.4 W3 真資料與有限數值核對

統籌的新增兩日 probe 是獨立2 GET／287,489 body bytes。後續 **first POST 是 actual API 的3105／9/30**，新觀測一次取得24原件、body合計3,191,051 bytes；44 selected原列／968金融原字串、全欄 int64及組成／total逐一核對，9/1、9/2 body hash與 probe一致。兩月正 OHLC及完整22日核通，三截止36 net均以原件 buy－sell獨立重算。API 共1,350次重複的 window buy／sell／net字串核對一致，這不是1,350個 distinct raw欄位；6組 detail.overview與直接overview、cutoff／版本／batch相等。

本次有限參考只集中於此表，順序為外資（不含外資自營商）／投信／自營商、單位股；10/2數值保留 W1／W2已驗基準：

| 標的 | cutoff | 5日 net | 20日 net |
| --- | --- | --- | --- |
| 3105 | 2026-09-30 | `[16854574, 2227000, 975486]` | `[19834870, 17802588, 1159585]` |
| 3105 | 2026-10-01 | `[10450479, 3045800, 345161]` | `[11360445, 16718388, -227745]` |
| 3105 | 2026-10-02 | `[21655769, 2223800, 1578271]` | `[25496297, 16596388, 1183894]` |
| 6488 | 2026-09-30 | `[-3715832, 180211, 77751]` | `[-8274270, -2271295, -104392]` |
| 6488 | 2026-10-01 | `[-7671733, 1177490, 60743]` | `[-14064055, -1335785, -142974]` |
| 6488 | 2026-10-02 | `[-2452286, 920329, 229491]` | `[-13191795, -1012703, 261501]` |

驗收 reader exit0／guard0，import／普通 GET外網0，native repeat POST與最後讀回仍 held同24份原件，19表全欄／typeof至 shutdown不變。命令、UTC、full hashes、原始失敗及修正留原 task；未保存 raw，沒有磁碟／跨程序重播。範圍外來源／日期／標的／TWSE、修訂／PIT、研究條件及完整 M1仍缺。此觀測不准入8/31 daily或8月 index；後續 W4新增範圍與新觀測另見§15。

## 15. M1-W4：四截止法人來源與全月日曆核對

本節保留W4歷史觀測、policy與原數值；現行W5五截止／24日曆見[§16](#16-m1-w5五截止法人來源與完整有界日曆)，不沿本節pins放行新範圍。

**新增真來源、四截止計算、actual API及兩股四截止原生表單操作已有限接受。** 範圍為 TPEx 3105／6488、2026-09-29／09-30／10-01／10-02；日曆限2026-08-31～10-02。W4新增8/31 daily與8月 index，完整有界23 sessions已由真原件正面核實。具名個股操作及未驗邊界見[§20](STOCK_RESEARCH_PAGE.md#20-m1-w4四截止法人窗口與原件追溯)；W1／W3 policy與觀測保留為歷史，不作本版設定。

### 15.1 新版 policy、來源與有界取得

Worker為 `tpex-institutional-window/w4-v1`，profile `free_public_local`；外部 pins為 `policy_version=m1-w4-tpex-window-2026-10-04.1`、`policy_digest=sha256:576e72676c23efedd3fc857a90e57c2e58f438a8669ba39dea2faa132f7616df`，canonical policy為3509 UTF-8 bytes。整份 policy／來源集合／四用途、四個 `supported_cutoffs`及固定 digest須一致，不以舊 pins放行新範圍。原 registry／P2a manifest／bundled pins未改。

| Source ID | W4來源版本與准入查詢 |
| --- | --- |
| `tpex_government_institutional_csv` | `dataset-11856-dated-csv-observed-2026-10-04/v3`；沿[§13.1](#131-獨立-policy-與四用途)的 dataset11856 exact GET，`d=115/MM/DD`僅8/31～10/2的23個 expected sessions。 |
| `tpex_government_index_csv` | `dataset-11391-month-csv-observed-2026-10-04/v2`；沿§13.1的 dataset11391 exact GET，`date=2026/08/01`／`2026/09/01`／`2026/10/01`；全返回月列先驗，再採有界日期。 |

政府開放授權／TPEx署名及原始成交統計基礎沿§13.1／13.3；`local_fetch`／`raw_store`／`summarize`僅本 policy範圍 admitted，`historical_pit=unsupported`。准入 raw_store不授權本輪落盤，原件只存 process memory；未放行其他日期、TWSE或任意自動下載。

一次明示 load最多26 GET（23 daily＋3 month）；daily≤2 MiB、index≤1 MiB、總≤49 MiB（51,380,224 bytes），每 request timeout15秒、identity encoding、零 retry／redirect。日曆失敗不續取 daily；一次嘗試後不重取、refresh或較早 fallback。import／snapshot／普通 GET零外網、不寫檔／DB。數字 rate limit、整批 hard deadline及跨程序 rate limiter仍未提供。

### 15.2 全月核對與有界採用分開

日曆為 `tpex-2026-08-31_2026-10-02-weekdays-11503027221/v1`；沿既有周一至五規則及9/25、9/28明示閉日，不由缺列推休市。三月原件共43列：8月21、9月20、10月2。每一返回列均驗 exact六欄、requested month、日期≤10/2、日期唯一、平日、有限正 OHLC及上下界；漲跌另驗有限數值。任一界線前列壞值／錯月／重複亦拒整份日曆，不因未採用而略過檢核。

`validation_scope=all_returned_month_rows`；8月 `candidate_count=21`、`adopted_count=1`、`pre_calendar_row_count=20`。8/31以前20列已驗但未採入 W4日曆／窗口；8/31為月原列21。界線內正面集合須恰好等於23個 expected sessions，缺月／缺日、額外／休市衝突或競爭版本均使日曆與全部窗口 unavailable。全月 OHLC核對不等於界線前 daily已取得或已准入，也不外推全年／其他市場。

計算版本 `independent-net-sum/expected-session-inclusive-v1`未變；每窗只取≤所選 cutoff的 required sessions，union較晚原件不入較早窗口。

| cutoff | 截止內 sessions | 5日起點 | 20日起點 |
| --- | ---: | --- | --- |
| 2026-09-29 | 20 | 2026-09-21 | 2026-08-31 |
| 2026-09-30 | 21 | 2026-09-22 | 2026-09-01 |
| 2026-10-01 | 22 | 2026-09-23 | 2026-09-02 |
| 2026-10-02 | 23 | 2026-09-24 | 2026-09-03 |

### 15.3 原件與按窗口拒用

§13.3的25欄／全列日期、欄數、唯一代碼及非空名稱，selected兩股各22金融欄 canonical int64／七組 buy－sell／組成與 total gate、股單位及任意精度窗口 sum不變。金融值檢核限兩股，不稱其他標的金融數值已驗。缺／錯／壞日、selected缺列、hash／receipt不合格或競爭 revision只拒需要該日的窗口；不補零、縮窗、挑版或採較早／未來替代。Policy／日曆壞則全部拒用。

各窗仍列 required／valid／missing／invalid dates、原因、原列／版本／hash及UTC收據，讀回重驗同 immutable bytes。published／first available／revision time與下載修訂保障／lineage仍 unknown；本次資料日期事後統計不是 PIT、Signal／研究條件、原件保存或跨程序重播。

### 15.4 W4真資料與唯一48 net參考

新增來源 probe為獨立2 GET／146,823 body bytes：8/31 daily903列、兩股44金融原字串；8月21列全 OHLC已核。後續 **first actual API POST為3105／9/29**，新觀測一次取得26原件／3,337,874 body bytes。23 daily共20,763列的日期／code／name／width全核；兩股46 selected rows／1012金融原字串、int64及全部關係逐欄核通。三月43列全 OHLC及有界23日期核通，新增兩原件 body hash與 probe相符；probe及 production capture／receipt分開，合計外部28 GET不是單批28原件或 process峰值。

四截止48 net皆由原件 buy－sell獨立重算；actual API共1800次 window buy／sell／net字串逐欄一致，不當作1800個 distinct raw欄位。兩股四截止的8組 held POST detail.overview與直接overview同 cutoff／版本／batch，source request_count保持26、19表全欄／typeof不變、guard0。首次 checker誤呼不存在的 GET endpoint得404，改用既有 held POST後 exit0且無新 source GET；原失敗留 task。

本版有限參考只集中於此表；順序為外資（不含外資自營商）／投信／自營商，單位股。其他三 cutoff的36值保留 W3真值基準：

| 標的 | cutoff | 5日 net | 20日 net |
| --- | --- | --- | --- |
| 3105 | 2026-09-29 | `[1233280, 2655000, -140568]` | `[709262, 18045588, 543694]` |
| 3105 | 2026-09-30 | `[16854574, 2227000, 975486]` | `[19834870, 17802588, 1159585]` |
| 3105 | 2026-10-01 | `[10450479, 3045800, 345161]` | `[11360445, 16718388, -227745]` |
| 3105 | 2026-10-02 | `[21655769, 2223800, 1578271]` | `[25496297, 16596388, 1183894]` |
| 6488 | 2026-09-29 | `[-8857542, 285175, -12038]` | `[-13581580, -3551184, -446637]` |
| 6488 | 2026-09-30 | `[-3715832, 180211, 77751]` | `[-8274270, -2271295, -104392]` |
| 6488 | 2026-10-01 | `[-7671733, 1177490, 60743]` | `[-14064055, -1335785, -142974]` |
| 6488 | 2026-10-02 | `[-2452286, 920329, 229491]` | `[-13191795, -1012703, 261501]` |

具名原生四截止操作與收尾界線見[個股頁 §20](STOCK_RESEARCH_PAGE.md#20-m1-w4四截止法人窗口與原件追溯)，驗證入口見[開發文件](development-baseline/README.md#m1-w4-四截止法人窗口的零落盤驗證入口)。命令、UTC、full hashes與原失敗留原 task；未保存 raw。範圍外日期／標的／TWSE、PIT／修訂、研究條件與完整 M1仍缺。W4當時只選題8/28 daily候選、未取得或准入該日；W5後續獨立觀測見§16，本節原值保留歷史。

## 16. M1-W5：五截止法人來源與完整有界日曆

**新8/28真來源、24日曆、五截止計算、actual API及兩股各五截止可信原生操作已有限接受。** 支持 TPEx3105／6488、2026-09-24／09-29／09-30／10-01／10-02；日曆限2026-08-28～10-02。W1–W4的policy、觀測與數值保留歷史，不作本版設定；具名操作見[個股頁 §21](STOCK_RESEARCH_PAGE.md#21-m1-w5五截止法人窗口與原件追溯)。

### 16.1 新版policy、用途與取得上限

Worker `tpex-institutional-window/w5-v1`，profile `free_public_local`；外部pins為 `policy_version=m1-w5-tpex-window-2026-10-05.1`、`policy_digest=sha256:e78104735c815801a73fe9eab78fcabf2e9a79a61ab74d3fe3e80fa206129643`，canonical policy3535 UTF-8 bytes。整份policy／來源集合／四用途／五個supported cutoffs與digest須一致，不沿舊pins放行新範圍；原registry／P2a manifest／bundled pins未改。

| Source ID | W5來源版本與准入查詢 |
| --- | --- |
| `tpex_government_institutional_csv` | `dataset-11856-dated-csv-observed-2026-10-05/v4`；沿[§13.1](#131-獨立-policy-與四用途)的dataset11856 exact GET，`d=115/MM/DD`只取8/28～10/2的24個expected sessions。 |
| `tpex_government_index_csv` | `dataset-11391-month-csv-observed-2026-10-05/v3`；沿§13.1的dataset11391 exact GET，`date=2026/08/01`／`2026/09/01`／`2026/10/01`；全返回月列先驗，再採有界日期。 |

來源版本的observed date以Asia/Taipei明示為2026-10-05；精確取得時間另記UTC，不把UTC的2026-10-04誤當臺北觀測日。政府開放授權／TPEx署名、原始成交統計基礎及外資不重加口徑沿§13.1／13.3；`local_fetch`／`raw_store`／`summarize`僅本policy範圍admitted，`historical_pit=unsupported`。raw_store准入不授權本輪落盤，原件只存process memory；其他日期／標的金融值、TWSE或任意自動下載未放行。

一次明示load最多27 GET＝3 month＋24 daily；daily≤2 MiB、index≤1 MiB、總≤51 MiB（53,477,376 bytes），每request timeout15秒、identity encoding、retry0／redirect0。日曆失敗不續取daily；一次嘗試後不重取、refresh或較早fallback。import／snapshot／普通GET零外網、不寫檔／DB。數字rate limit、整批hard deadline及跨程序rate limiter仍未提供。

### 16.2 全月驗證、24日曆與各截止窗口

Calendar `tpex-2026-08-28_2026-10-02-weekdays-11503027221/v1`；沿既有周一至五規則及9/25、9/28明示閉日，不由缺列推休市。三月43列＝8月21、9月20、10月2，全部返回列須驗exact六欄、requested month、日期≤10/2、唯一／平日、有限正OHLC與上下界，漲跌為有限數值。界線前列壞值、錯月或重複亦拒整份日曆。

`validation_scope=all_returned_month_rows`；8月candidate21／adopted2／pre-calendar19，採8/28及8/31；8/27以前19列已驗但未採入W5日曆／窗口。界線內正面集合須恰好等於24個expected sessions；缺月／缺日、額外日期／閉日衝突或競爭版本使日曆與全部窗口unavailable。界線前index OHLC已驗不代該日法人daily或新的用途准入。

計算版本 `independent-net-sum/expected-session-inclusive-v1`未變。每窗只取≤cutoff的required sessions；union較晚日不入較早窗口。

| cutoff | 截止內sessions | 5日起點 | 20日起點 |
| --- | ---: | --- | --- |
| 2026-09-24 | 20 | 2026-09-18 | 2026-08-28 |
| 2026-09-29 | 21 | 2026-09-21 | 2026-08-31 |
| 2026-09-30 | 22 | 2026-09-22 | 2026-09-01 |
| 2026-10-01 | 23 | 2026-09-23 | 2026-09-02 |
| 2026-10-02 | 24 | 2026-09-24 | 2026-09-03 |

### 16.3 原件、精確整數與按窗口拒用

§13.3的25欄／全列日期、欄數、唯一代碼及非空名稱，selected兩股各22金融欄canonical int64、七組buy－sell／外資與自營商組成／total關係、股單位及任意精度窗口sum不變。金融值檢核限兩股，不稱其他標的金融數值已驗。缺／錯／壞日、selected缺列、hash／receipt不合格或競爭revision，只拒需要該日的窗口；不補零、縮窗、挑版或採較早／未來替代。Policy／日曆壞則全部拒用。

各窗列required／valid／missing／invalid dates、原因、原列／版本／hash及UTC收據，讀回重驗同immutable bytes。published／first available／revision time及下載修訂保障／lineage仍unknown；本次事後統計不是PIT、Signal／研究條件、原件保存或跨程序重播。

### 16.4 真來源、獨立觀測與唯一60 net參考

`SRC-W5-PROBE-1`首exit0：獨立4 GET／150,072 body bytes。新8/28 dated CSV147,516B，body SHA256=`9b5685be891106979c54043832d1eb0acec99ee17a029a58aa22087df10241a4`；917列／25欄header、全日期1150828、unique codes／width／names核通。兩股44金融原字串、canonical int64及全部關係核通；3105穩懋raw ordinal175，6488環球晶652。三index原件8月1221B／21列、9月1170B／20列、10月165B／2列；全43月列及完整24日曆正面核通。Probe UTC2026-10-04T16:13:40.248714～16:13:40.778349+00:00，Asia/Taipei為2026-10-05T00:13:40.248714～00:13:40.778349+08:00。

後續 **first actual API POST為3105／9/24**，新觀測一次取得27原件／3,485,390 body bytes；UTC2026-10-04T16:34:12.460839～16:34:34.024462+00:00，臺北2026-10-05T00:34:12.460839～00:34:34.024462+08:00。24 daily共21,680全列的日期／code／name／width核通；兩股48 selected rows／1056金融原字串、int64及全部關係逐欄核通。三月43列全OHLC、採24日期及界線前19列核通；新8/28 body hash與probe相符。Probe4與production27的capture／receipt分開，合計31 external GET不是一批31原件或process峰值。

五截止60 net皆由原件buy－sell獨立重算；actual API共2250次重疊window buy／sell／net字串逐欄一致，不當作2250個distinct raw欄位。兩股10組held POST／detail GET／overview GET採同cutoff／版本／batch，source request_count保持27；19表全欄／typeof不變、guards0。具名原生表單另核60 DOM net；十組source outer SUMMARY的required dates及1800 raw金融字串核對是另一組DOM證據，不與2250 API字串或1056 distinct selected欄位混算。

本版唯一60值集中於此表；順序為外資（不含外資自營商）／投信／自營商，單位股。其餘四cutoff的48值與W4基準一致，W4原表仍保留歷史：

| 標的 | cutoff | 5日net | 20日net |
| --- | --- | --- | --- |
| 3105 | 2026-09-24 | `[11619934, 2453900, 554128]` | `[3598977, 20383588, 492586]` |
| 3105 | 2026-09-29 | `[1233280, 2655000, -140568]` | `[709262, 18045588, 543694]` |
| 3105 | 2026-09-30 | `[16854574, 2227000, 975486]` | `[19834870, 17802588, 1159585]` |
| 3105 | 2026-10-01 | `[10450479, 3045800, 345161]` | `[11360445, 16718388, -227745]` |
| 3105 | 2026-10-02 | `[21655769, 2223800, 1578271]` | `[25496297, 16596388, 1183894]` |
| 6488 | 2026-09-24 | `[-7696805, 222092, 103774]` | `[-14680682, -3475784, -500087]` |
| 6488 | 2026-09-29 | `[-8857542, 285175, -12038]` | `[-13581580, -3551184, -446637]` |
| 6488 | 2026-09-30 | `[-3715832, 180211, 77751]` | `[-8274270, -2271295, -104392]` |
| 6488 | 2026-10-01 | `[-7671733, 1177490, 60743]` | `[-14064055, -1335785, -142974]` |
| 6488 | 2026-10-02 | `[-2452286, 920329, 229491]` | `[-13191795, -1012703, 261501]` |

來源／API／具名native有限接受，不證範圍外日期／標的／TWSE、PIT／修訂、研究條件或完整M1；原件未落盤。原失敗、full hashes及逐次UTC收據留原task；入口及服務清理見[開發文件](development-baseline/README.md#m1-w5-五截止法人窗口的零落盤驗證入口)。下一M1-W6的8/27 daily尚未取得／准入，不能由界線前index正面OHLC或本版pins放行。

## 17. M1-W6：六截止法人來源與完整有界日曆

**新8/27真來源、25日曆、六截止計算、actual API及兩股具名可信原生操作已有限接受；owned page／服務已核清。** 支持TPEx3105／6488、2026-09-23／09-24／09-29／09-30／10-01／10-02，日曆限2026-08-27～10-02。W1–W5各自policy／觀測／數值保留歷史，本版不沿舊pins；產品界線見[個股頁 §22](STOCK_RESEARCH_PAGE.md#22-m1-w6六截止法人窗口與原件追溯)。

### 17.1 新版policy、用途與取得上限

Worker `tpex-institutional-window/w6-v1`，profile `free_public_local`；外部pins為 `policy_version=m1-w6-tpex-window-2026-10-05.1`、`policy_digest=sha256:b9d5377278eb3c70f94ff994c7e43a48ca82198a0fabb21ec30b87e535c1c3fc`，canonical policy3561 UTF-8 bytes。完整policy／來源集合／四用途／六supported cutoffs及digest須一致；bundled registry／P2a manifest不變，新範圍不得由舊version／pins放行。

| Source ID | W6版本與准入查詢 |
| --- | --- |
| `tpex_government_institutional_csv` | `dataset-11856-dated-csv-observed-2026-10-05/v5`；沿[§13.1](#131-獨立-policy-與四用途)的dataset11856 exact GET，`d=115/MM/DD`只取8/27～10/2的25 expected sessions。 |
| `tpex_government_index_csv` | `dataset-11391-month-csv-observed-2026-10-05/v4`；沿§13.1的dataset11391 exact GET，`date=2026/08/01`／`2026/09/01`／`2026/10/01`，先驗全部返回月列再採有界日期。 |

版本observed date依actual Asia/Taipei2026-10-05，精確取得時間另列UTC，不由branch或UTC日期推定。政府開放授權、TPEx署名、原始成交統計及外資不重加口徑沿§13.1／13.3；`local_fetch`／`raw_store`／`summarize`僅本policy範圍admitted，`historical_pit=unsupported`。raw_store准入不授權本輪落盤，原件只存process memory；其他日期／標的金融值、TWSE或任意自動下載未放行。

一次明示load最多28 GET＝3 month＋25 daily；daily≤2 MiB、index≤1 MiB、總≤53 MiB（55,574,528 bytes），每request timeout15秒、identity encoding、retry0／redirect0。日曆失敗不續取daily；一次嘗試後不重取、refresh或較早fallback。import／snapshot／普通GET零外網、不寫檔／DB。數字rate limit、整批hard deadline及跨程序rate limiter仍未提供。

### 17.2 全月驗證、25日曆與六截止

Calendar `tpex-2026-08-27_2026-10-02-weekdays-11503027221/v1`；周一至五及9/25、9/28明示閉日不變，不由缺列推休市。三月43列＝8月21、9月20、10月2；全部返回列須驗exact六欄、requested month、日期≤10/2、唯一／平日、有限正OHLC及上下界，漲跌有限。界線前壞值、錯月／重複亦拒整份日曆。

`validation_scope=all_returned_month_rows`；8月candidate21／adopted3／pre-calendar18，只採8/27／8/28／8/31；其餘18列已驗未採。界線內正面集合須恰等25 expected sessions；缺月／缺日、額外日期／閉日衝突或競爭版本使全部窗口unavailable。界線前index不代法人daily或用途准入。

計算版本 `independent-net-sum/expected-session-inclusive-v1`未變，每窗只採≤cutoff的required sessions；union較晚日不入較早窗口。

| cutoff | 截止內sessions | 5日起點 | 20日起點 |
| --- | ---: | --- | --- |
| 2026-09-23 | 20 | 2026-09-17 | 2026-08-27 |
| 2026-09-24 | 21 | 2026-09-18 | 2026-08-28 |
| 2026-09-29 | 22 | 2026-09-21 | 2026-08-31 |
| 2026-09-30 | 23 | 2026-09-22 | 2026-09-01 |
| 2026-10-01 | 24 | 2026-09-23 | 2026-09-02 |
| 2026-10-02 | 25 | 2026-09-24 | 2026-09-03 |

### 17.3 原件、精確整數與按窗口拒用

§13.3的25欄、全列日期／欄數／唯一代碼／非空名稱、selected兩股各22金融欄canonical int64、七組buy－sell／外資及自營商組成／total關係、股單位及任意精度sum不變。代碼符合 `[0-9A-Z]{4,6}`，不要求其他全列代碼純數字；其他標的金融值未驗。缺／錯／壞日、selected缺列、hash／receipt不合格或競爭revision只拒需要該日的窗口；不補零、縮窗、挑版或較早／未來替代，policy／日曆壞則全部拒用。

各窗列required／valid／missing／invalid dates、原因、原列／版本／hash與UTC收據，讀回重驗同immutable bytes。published／first available／revision time及修訂保障／lineage仍unknown；本次事後統計非PIT、trend／研究條件、原件保存或跨程序重播。

### 17.4 獨立觀測與唯一72 net參考

`SRC-W6-PROBE-1`獨立4 GET／147,446 body bytes；新8/27 dated CSV144,890B，body SHA256=`85aa6d97bcddade835587145c7fa8c49c3ecbc981233144630060bc30692993d`，905全列／25欄、日期1150827及code／name／width核通；兩股44金融原字串／int64及全部關係核通，raw ordinal3105穩懋176、6488環球晶647。三index為1221／1170／165B，全部43月列、採25日曆及界線前18列已核，memory disk guards0；Probe UTC2026-10-04T18:09:17.797975～18:09:18.301571+00:00，臺北2026-10-05T02:09:17.797975～02:09:18.301571+08:00。

後續first actual API POST為3105／9/23，新觀測一次取得28原件／3,630,280 body bytes；UTC2026-10-04T18:32:29.556157～18:32:38.132362+00:00，臺北2026-10-05T02:32:29.556157～02:32:38.132362+08:00。25 daily共22,585全列結構、50 selected rows／1100金融原字串及全部關係逐欄核通；三月43 full OHLC、採25／界線前18核通。Raw base64／28份全部body SHA及receipt元數據的URL／method／status／content-type／identity／UTC／policy與v5及v4已獨立核；未主張全部28份receipt digest獨立重算。新8/27 daily request_started_at=2026-10-04T18:32:29.643156+00:00、captured_at=18:32:29.961421+00:00，臺北為2026-10-05T02:32:29.643156～02:32:29.961421+08:00；新8/27 hash與probe相同但capture／receipt分開；probe4＋production28共32 external GET不是一批32原件或process峰值。

兩股六截止72 net由原件buy－sell獨立重算；actual API共2700次重疊window buy／sell／net字串逐欄一致，不稱2700 distinct raw欄位。detail.overview／overview／capture wrapper採同cutoff／版本／held28 batch，repeat POST／GET外網0；19 memory表全部欄／typeof不變、guards0。具名可信native另核12組日期表單／72 DOM net及5／20日起迄／missing0；12組source outer SUMMARY的20 required dates及180金融原字串逐組核通，共2160 DOM金融欄，不混API2700或1100 distinct selected欄位，不稱全部daily子表曾原生展開。兩股390×844新8/27可信原列及拒用界線見個股頁§22。

本版唯一72值集中此表，順序外資（不含外資自營商）／投信／自營商，單位股；原五cutoff60值與W5一致，歷史表仍保留：

| 標的 | cutoff | 5日net | 20日net |
| --- | --- | --- | --- |
| 3105 | 2026-09-23 | `[8051509, 3386100, 1291688]` | `[4039680, 21243975, 1345760]` |
| 3105 | 2026-09-24 | `[11619934, 2453900, 554128]` | `[3598977, 20383588, 492586]` |
| 3105 | 2026-09-29 | `[1233280, 2655000, -140568]` | `[709262, 18045588, 543694]` |
| 3105 | 2026-09-30 | `[16854574, 2227000, 975486]` | `[19834870, 17802588, 1159585]` |
| 3105 | 2026-10-01 | `[10450479, 3045800, 345161]` | `[11360445, 16718388, -227745]` |
| 3105 | 2026-10-02 | `[21655769, 2223800, 1578271]` | `[25496297, 16596388, 1183894]` |
| 6488 | 2026-09-23 | `[-7129861, 121692, 168117]` | `[-12192815, -3478626, -182918]` |
| 6488 | 2026-09-24 | `[-7696805, 222092, 103774]` | `[-14680682, -3475784, -500087]` |
| 6488 | 2026-09-29 | `[-8857542, 285175, -12038]` | `[-13581580, -3551184, -446637]` |
| 6488 | 2026-09-30 | `[-3715832, 180211, 77751]` | `[-8274270, -2271295, -104392]` |
| 6488 | 2026-10-01 | `[-7671733, 1177490, 60743]` | `[-14064055, -1335785, -142974]` |
| 6488 | 2026-10-02 | `[-2452286, 920329, 229491]` | `[-13191795, -1012703, 261501]` |

來源／計算／actual API／具名native已有限接受，不證範圍外／TWSE、PIT／修訂、trend／研究條件、raw保存／跨程序讀回或完整M1。Root首probe因未明示shared deps的httpx ModuleNotFoundError exit1／無寫，補shared Python3.12.14／httpx0.28.1後exit0；只讀核對首誤code純數字AssertionError exit1、再誤detail直取institutional_windows KeyError exit1，修正正規及detail.overview.institutional後exit0；未重取來源或寫檔。完整原錯、hash與逐次UTC留原task。下一W7候選新增9/22／保六cutoff，8/26 daily尚未取得／准入；候選26sessions／29GET／55MiB、9/22恰20、5日起9/16／20日起8/26，須新來源／policy／pins正面，不由本版放行；驗證／服務清理見[開發文件](development-baseline/README.md#m1-w6-六截止法人窗口的零落盤驗證入口)。

## 18. M1-W7：七截止法人來源與完整有界日曆

**新8/26真來源、完整26日曆、七截止84 net／actual API及兩股具名可信native已有限接受；owned page／服務清理已核。** 支持TPEx3105／6488、2026-09-22／09-23／09-24／09-29／09-30／10-01／10-02，日曆限2026-08-26～10-02。§13–17均保留當時版本／觀測／數值；§17的72值本輪逐值匹配，不作implicit latest或放行新範圍。產品界線見[個股頁 §23](STOCK_RESEARCH_PAGE.md#23-m1-w7七截止法人窗口與原件追溯)。

### 18.1 新版policy、用途與取得上限

Worker `tpex-institutional-window/w7-v1`，profile `free_public_local`；外部pins為 `policy_version=m1-w7-tpex-window-2026-10-05.1`、`policy_digest=sha256:4ef122b1cc391f9faa85bf72b3441d993a037ccd0a18a31afe2ae2f0e6986c90`，canonical policy3587 UTF-8 bytes。完整policy／來源集合／四用途／七supported cutoffs及digest須一致；bundled registry／P2a manifest不變，舊version／pins不放行本版。

| Source ID | W7版本與准入查詢 |
| --- | --- |
| `tpex_government_institutional_csv` | `dataset-11856-dated-csv-observed-2026-10-05/v6`；沿[§13.1](#131-獨立-policy-與四用途)的dataset11856 exact GET，`d=115/MM/DD`僅8/26～10/2的26 expected sessions，不需8/25。 |
| `tpex_government_index_csv` | `dataset-11391-month-csv-observed-2026-10-05/v5`；沿§13.1的dataset11391 exact GET，`date=2026/08/01`／`2026/09/01`／`2026/10/01`，先驗全部返回月列再採有界日期。 |

Observed版號依actual Asia/Taipei2026-10-05；取得／capture時間另列UTC與臺北時間，不從branch或UTC日期推定。政府開放授權、TPEx署名、原始成交／外資不重加口徑沿§13.1／13.3；`local_fetch`／`raw_store`／`summarize`僅此policy admitted，`historical_pit=unsupported`。raw_store准入不授權本輪磁碟保存，原件只存process memory；其他標的金融值、日期、TWSE或任意自動下載未放行。

一次明示load最多29 GET＝3 month＋26 daily；daily≤2 MiB、index≤1 MiB、總≤55 MiB（57,671,680 bytes），每request timeout15秒、identity encoding、retry0／redirect0。日曆失敗不續取daily；一次嘗試後不重取、refresh或較早fallback。import／snapshot／普通GET零外網，不寫檔／DB；數字rate limit、整批hard deadline及跨程序rate limiter仍未提供。

### 18.2 全月驗證、26日曆與七截止

Calendar `tpex-2026-08-26_2026-10-02-weekdays-11503027221/v1`；周一至五與9/25、9/28 closure11503027221明示閉日，不由缺列推休市。全部三月43列＝8月21／9月20／10月2，先驗exact六欄、requested month、日期≤10/2、唯一／平日、有限正OHLC及上下界與有限漲跌；界線前壞值、錯月或重複也拒整份日曆。

`validation_scope=all_returned_month_rows`；8月candidate21／adopted4／pre-calendar17，只採8/26／8/27／8/28／8/31；9月20／20、10月2／2，其餘17列已驗未採。界線內正面集合須恰等26 expected sessions；缺月／日、額外日期／閉日衝突或競爭版本使全部窗口unavailable。界線前index不代法人daily／用途准入。

計算版本 `independent-net-sum/expected-session-inclusive-v1`未變，每窗只採≤cutoff的required sessions；union較晚日不入較早窗口。

| cutoff | 截止內sessions | 5日起點 | 20日起點 |
| --- | ---: | --- | --- |
| 2026-09-22 | 20 | 2026-09-16 | 2026-08-26 |
| 2026-09-23 | 21 | 2026-09-17 | 2026-08-27 |
| 2026-09-24 | 22 | 2026-09-18 | 2026-08-28 |
| 2026-09-29 | 23 | 2026-09-21 | 2026-08-31 |
| 2026-09-30 | 24 | 2026-09-22 | 2026-09-01 |
| 2026-10-01 | 25 | 2026-09-23 | 2026-09-02 |
| 2026-10-02 | 26 | 2026-09-24 | 2026-09-03 |

### 18.3 原件、精確整數與按窗口拒用

§13.3的25欄、全列日期／欄數／唯一合法code `[0-9A-Z]{4,6}`／非空名稱、selected兩股各22金融欄canonical int64、七組buy－sell／外資、自營商及total關係、股單位與任意精度sum不變；其他標的金融值未驗。缺／錯／壞日、selected缺列、hash／receipt不合格或競爭revision只拒需要該日的窗口；不補零、縮窗、挑版或較早／未來替代，policy／日曆壞則全部拒用。

各窗列required／valid／missing／invalid dates、原因、原列／版本／hash及UTC收據，讀回重驗同immutable bytes。published／first available／revision time、修訂保障／lineage仍unknown；事後統計非PIT、trend／研究條件、Signal接線、原件保存或跨程序重播。

### 18.4 獨立觀測與唯一84 net參考

`ROOT-W7-PROBE-1`已取得1 body後，ZoneInfo formatter因缺tzdata exit1，未完成全驗、body bytes／hash收據未知；`ROOT-W7-PROBE-2`另為獨立4 GET／146,640 body bytes，UTC2026-10-04T20:01:46.761254～20:01:47.962587+00:00，臺北2026-10-05T04:01:46.761254～04:01:47.962587+08:00。新8/26 dated CSV144,084B，body SHA256=`0fa67509a1901d865d4951a85cdf87643c4cccbcc8eeafcbb9a08e648b10d107`；日期1150826、900全列／25欄、兩股44金融原字串／全部關係，ordinal3105=175／6488=637已核。三月43 full OHLC先驗、採26／界線前17，來源gate正面後才實作。這不是傳輸retry或單批5原件。

First actual API POST為3105／9/22，production為新觀測29 GET／3,774,364 body bytes；UTC2026-10-04T20:24:34.510799～20:24:44.390171+00:00，臺北2026-10-05T04:24:34.510799～04:24:44.390171+08:00。新8/26 daily request_started_at=2026-10-04T20:24:34.698797+00:00、captured_at=20:24:35.069009+00:00；臺北為2026-10-05T04:24:34.698797～04:24:35.069009+08:00，不能使用Oct index的20:24:34.696796作daily結束。Body與probe2相同，capture／receipt各自獨立。1失敗probe＋4成功probe＋29 production共34 external GET，分三觀測，不稱單批34、全部34 body bytes已知或process峰值。

Production26 daily共23,485全列結構、52 selected rows／1144金融原字串及全部canonical int64／關係逐欄核通；三月43 full OHLC／採26／界線前17已核。Root獨立核held29 raw base64／全部body SHA、exact URL／method／HTTP200／MIME／identity／UTC／source version／policy與外pin；**本W7全部29份receipt SHA均獨立canonical重算**，不沿用W6未全重算receipt digest的限制。

兩股七截止84 net全部以原件buy－sell獨立重算；原六cutoff72值與§17一致。Same-cutoff detail.overview.institutional／overview／capture wrapper／repeat POST逐欄核通，共3150次重疊window金融原字串，不稱3150 distinct raw欄位。Root browser前具名local範圍為32 GET／15 POST，不含後續browser總數；repeat POST held29，普通GET／import零外網，19 memory表全欄／typeof不變、guards0，catalog／price seed僅synthetic，不證正式DB或真行情。

具名native另核14組unique日期form／84 DOM net及5／20日起迄／actual missing0；14組outer SUMMARY各20 required daily≤cutoff及180金融原字串，共2520 DOM金融欄，不混1144 distinct selected或3150 API重疊欄、不稱全部20 nested日子表曾原生展開。兩股390×844新8/26原列、拒用及操作限制見個股頁§23。

本版唯一84值集中此表，順序外資（不含外資自營商）／投信／自營商，單位股；§17歷史72值仍原byte保留：

| 標的 | cutoff | 5日net | 20日net |
| --- | --- | --- | --- |
| 3105 | 2026-09-22 | `[12383787, 2617100, 1844118]` | `[11235554, 24828975, 1650797]` |
| 3105 | 2026-09-23 | `[8051509, 3386100, 1291688]` | `[4039680, 21243975, 1345760]` |
| 3105 | 2026-09-24 | `[11619934, 2453900, 554128]` | `[3598977, 20383588, 492586]` |
| 3105 | 2026-09-29 | `[1233280, 2655000, -140568]` | `[709262, 18045588, 543694]` |
| 3105 | 2026-09-30 | `[16854574, 2227000, 975486]` | `[19834870, 17802588, 1159585]` |
| 3105 | 2026-10-01 | `[10450479, 3045800, 345161]` | `[11360445, 16718388, -227745]` |
| 3105 | 2026-10-02 | `[21655769, 2223800, 1578271]` | `[25496297, 16596388, 1183894]` |
| 6488 | 2026-09-22 | `[-1279737, -173308, 81702]` | `[-9048340, -4282803, -48947]` |
| 6488 | 2026-09-23 | `[-7129861, 121692, 168117]` | `[-12192815, -3478626, -182918]` |
| 6488 | 2026-09-24 | `[-7696805, 222092, 103774]` | `[-14680682, -3475784, -500087]` |
| 6488 | 2026-09-29 | `[-8857542, 285175, -12038]` | `[-13581580, -3551184, -446637]` |
| 6488 | 2026-09-30 | `[-3715832, 180211, 77751]` | `[-8274270, -2271295, -104392]` |
| 6488 | 2026-10-01 | `[-7671733, 1177490, 60743]` | `[-14064055, -1335785, -142974]` |
| 6488 | 2026-10-02 | `[-2452286, 920329, 229491]` | `[-13191795, -1012703, 261501]` |

有限接受不證範圍外／TWSE、修訂／PIT、trend／研究條件／Signal、raw保存／跨程序讀回或完整M1。原formatter失敗、逐次觀測／UTC／hash與驗證原錯留原task；測試與服務清理見[開發入口](development-baseline/README.md#m1-w7-七截止法人窗口的零落盤驗證入口)。下一M1-W8僅候選新增9/21／保七cutoff，新8/25 daily尚未取得／驗證／准入，須另核新完整日曆／policy／pins，不由本版放行。

## 19. M1-W8：八截止法人來源與完整有界日曆

**真8/25來源、完整27日曆、八截止96 net／actual API及兩股具名可信native已有限接受；owned page／服務清理已核。** 支持TPEx3105／6488、2026-09-21／09-22／09-23／09-24／09-29／09-30／10-01／10-02，日曆限2026-08-25～10-02。§13–18保留當時版本、觀測、數值及候選狀態；§18的84值本輪逐值匹配，不作implicit latest或放行新範圍。產品操作與未驗界線見[個股頁 §24](STOCK_RESEARCH_PAGE.md#24-m1-w8八截止法人窗口與原件追溯)。

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

### 19.4 獨立觀測與唯一96 net參考

`ROOT-W8-SOURCE-GATE-1` probe為獨立4 GET／146,055 body bytes，UTC2026-10-04T22:33:08.926360～22:33:09.479166+00:00，臺北2026-10-05T06:33:08.926360～06:33:09.479166+08:00。新8/25 dated CSV143,499B，body SHA256=`f053e20f576f37eb85e3215aeec00df50c083a43a0f4e9690c3515835459c794`；日期1150825、898全列／25欄、兩股44金融原字串／七組及全部關係，ordinal3105=175／6488=641已核。三月43 full OHLC先驗、採27／界線前16；正面來源gate後才實作。

First actual API POST為3105／9/21，production另為新觀測30 GET／3,917,863 body bytes；UTC2026-10-04T22:49:10.357308～22:49:20.531197+00:00，臺北2026-10-05T06:49:10.357308～06:49:20.531197+08:00。新8/25 daily request_started_at=2026-10-04T22:49:10.491309+00:00、captured_at=22:49:10.904309+00:00；臺北為2026-10-05T06:49:10.491309～06:49:10.904309+08:00。Body與probe相同，capture／receipt獨立；4 probe＋30 production共34 external GET為兩次觀測，不稱單批34或process峰值。

Production27 daily共24,383全列結構、54 selected rows／1188金融原字串及全部canonical int64／關係逐欄核通；三月43 full OHLC／採27／界線前16已核。Root獨立核held30全部body SHA、exact URL／method／HTTP200／CSV MIME／identity／UTC／source version／policy及external pins；全部30份raw base receipt SHA均獨立canonical重算。

兩股八截止96 net以原件buy－sell獨立重算，原七cutoff84值與HEAD §18逐值一致。Same-cutoff detail.overview.institutional／overview／capture wrapper／repeat POST逐欄核通，共3600次重疊window金融原字串，不稱3600 distinct raw欄位。具名root browser前local34 GET／33 POST，末端historical parser錯把`## 18.`與小節混拆導致assert0／exit1，前30 source／96 API及3600字串已核；修正唯讀2 GET／0 POST／source0後，全部84歷史值與ALL30 body／canonical receipt SHA核通exit0，不重POST或重取來源。普通GET／import零外網、held30，19 memory表全欄／typeof不變、guards0；catalog／price seed僅synthetic，不證正式DB或真行情。

Native另核16組unique可信日期form／96 DOM net及5／20日起迄／actual missing0；16組outer SUMMARY各20 required daily≤cutoff、180金融textContent逐欄對held30，共2880 DOM金融欄，不混1188 distinct selected或3600 API重疊欄，不稱20 nested日子表全曾原生展開。兩股390×844新8/25原列、repeat POST與拒用見個股頁§24。Node mock HTTP未跑；actual full App產品fetch／Response.json由上述具名native驗96 net。

本版唯一96值集中下表，順序外資（不含外資自營商）／投信／自營商，單位股；14個舊列依HEAD §18引用，歷史84值仍逐byte保留：

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

有限接受不證範圍外／TWSE、修訂／PIT、trend／研究條件／Signal、raw保存／跨程序讀回或完整M1。測試、原失敗／補驗及owned服務清理見[開發入口](development-baseline/README.md#m1-w8-八截止法人窗口的零落盤驗證入口)與原task；不改原exit或重跑已通驗收。下一M1-W9僅候選新增9/18／保八cutoff，新dataset11856 `d=115/08/24` daily尚未取得／驗證／准入；8/24全OHLC已驗未採不代daily，不需8/21。須下一新root另核新完整日曆／policy／pins／native，不由本版放行。

## 20. M1-PRICE-1：TPEx 兩股單日價格來源與准入

**來源、production capture／consumer、actual API及兩股具名可信操作已由root有限接受。** 範圍只限TPEx3105／6488、2026-10-05單日價量；本來源獨立於原四來源registry、P2a及W8法人policy。產品操作與未驗界線見[個股頁 §25](STOCK_RESEARCH_PAGE.md#25-m1-price-1上櫃兩股單日價量閉環有限接受)。

### 20.1 Exact資源、用途與固定policy

來源ID為 `tpex_11370_daily_close_csv`、source_version為 `tpex-11370/2026-10-05`；官方[dataset11370「上櫃股票行情」](https://data.gov.tw/dataset/11370)所連唯一exact GET資源為 [CSV](https://www.tpex.org.tw/web/stock/aftertrading/DAILY_CLOSE_quotes/stk_quote_result.php?l=zh-tw&o=data)。限公開免費本地使用、TPEx／stock／TWD、3105穩懋與6488環球晶、quote-date 2026-10-05；不外推其他stock／ETF／指數或新日期。

Wrapper須正面核對instrument的market=TW／exchange=TPEx、selected symbol＋exact known name、instrument類型為stock及etf_category為空，才可按兩股policy scope固定TWD。原Instrument未有currency欄，DB／model未改；未來若有currency欄且非TWD須拒用。此來源typed memory明示TWD，unknown／mixed來源與其他市場不猜幣別。

獨立嵌入policy `policy_version=m1-price-tpex-11370-2026-10-05.1`，canonical UTF-8 1462B，`policy_digest=sha256:452b9b8cfa3d050b79ea1a85b3e4ed643c40cf3d17882b8cb809ffdb7143deea`；完整policy／來源／範圍與digest須一致，root獨算已exit0。本次production沿同pins，既有TWSE／global registry、bundled default與法人pins維持。

准入依dataset11370的[政府資料開放授權條款第1版](https://data.gov.tw/license)及既有[TPEx網站條款](https://www.tpex.org.tw/zh-tw/gtsm_disclaimer.html?l=zh-tw)第7點政府開放資料例外；第5點的自動下載限制未由可讀endpoint略過。此exact政府資源的 `local_fetch`、`raw_store`、`summarize` 有限admitted，仍須有界取得、顯名、完整性、原件hash／版本／時間及traceability；本輪只process memory，raw_store准入沒有授權磁碟保存。署名保留「證期局＋櫃買中心／上櫃股票行情／2026／OGL1.0」，data-date為2026-10-05。不放行legacy POST、附加 `d` 的歷史查詢、其他URL或任意自動下載，`historical_pit=unsupported`。

每程序首次合法明示POST最多1外部GET；重複POST／普通GET／切股cache不新增外網，失敗cache不自動retry。body≤3MiB（3,145,728B）、deadline30秒、redirect0／retry0；固定 `expected_body_sha256=bdfcead65b5c36d2bd75d20fe7b790fa56ce39d2547d0772989243550ca36149`。URL無歷史日期參數，返回不同body／日期不得悄悄換版或重試。只有quote-date及observed capture；精確publication／first available／revision、rate limit及endpoint SLA仍未證實。

### 20.2 Root前置原件與兩股金融驗證

Root前置共2 GET：第一次選錯代碼欄位（row0是日期，應取row1代碼），未找到selected rows；第二次修正欄位後核同body，原錯誤／exit留原task。第二次HTTP200／application CSV、1,773,012B，12,060 data rows／18 fields，ROC `1151005` 對應2026-10-05、date-code唯一；金融驗證僅兩股。原body未落盤，capture UTC為 `2026-10-05T14:01:51.813710+00:00`，body SHA同上。

| Selected股／data列序（1-based）／含header行號 | O／H／L／C（元／股） | 成交股數（canonical股） | 日常成交量（張） | 成交金額（元） |
| --- | --- | --- | --- | --- |
| 3105穩懋／205／206 | 614／630／604／615 | 48127911 | 48,127.911 | 29694939981 |
| 6488環球晶／717／718 | 1220／1235／1175／1180 | 18982607 | 18,982.607 | 22887612060 |

原前置摘要把含header行206／718誤稱data ordinal，現核正為205／717；價量值不變。Root獨立CSV ordinal混用的assert exit1及修正exit0保留原task。此前置兩GET與下述production capture是不同觀測，不合稱一次POST或一批3GET。

### 20.3 Production唯一capture與有限接受

原native載入的trusted POST觸發唯一official GET、HTTP200：`request_started_at=2026-10-05T14:53:12.683229+00:00`、`captured_at=2026-10-05T14:53:13.943096+00:00`；body仍1,773,012B／12,060 data rows／18欄、SHA同§20.1。`receipt_sha256=abf32de2e110de56b24cb84fd776c42cbdbfd301a1b6f8c2f7f5c9a8ef8fc140`，policy原pins不變。Root獨立全結構、兩股12個金融cell、API／chart／audit與精確張逐值核通；不外推其他金融列。

兩股GET／重複POST使用同cache、0額外source；DB tables preserved=true，guards=0。原件／receipt只留memory，owned程序結束已釋放，無DB／raw file／HAR／截圖保存；bar id／raw_payload_id／ingestion_run_id為null。測試目錄及10/02資料是synthetic catalogue，只有本次official 10/05價格是actual；不證專案正式資料目錄、DB保存／跨程序、歷史close／日曆、完整M1或PIT。操作與清理分報見[個股頁 §25](STOCK_RESEARCH_PAGE.md#25-m1-price-1上櫃兩股單日價量閉環有限接受)／[開發入口](development-baseline/README.md#m1-price-1-單日價量的記憶體驗證入口)。

### 20.4 M2-FOCUS-LOTS-1 同來源的本輪觀測與採用

2026-10-06臺北的M2輪，root另作唯一fresh exact GET200：`request_started_at=2026-10-05T18:13:08.071535+00:00`、`captured_at=2026-10-05T18:13:08.907693+00:00`，body仍1,773,012B／12,060 data rows／18欄，固定body SHA與§20.1完全相同；本輪 `receipt_sha256=52acb105b78fc74ae56d29593f7f47616f6b54b11f541dd57f45f60e12c1377d`。Root獨立全結構、兩股12金融欄、exact名稱／普通stock／TPEx／TWD身分gate及精確股→張已核，source guards四項0。此為新的取得觀測，不覆寫§20.2／20.3原UTC或receipt；policy／source_version／用途准入與pins未變，資料日仍10/05，不稱10/06今日行情或PIT。

M2 consumer版本 `price-lot-focus/m2-v1` 以同程序TpexPriceStore採用合格兩股成交量，按精確張門檻給可追溯理由與同cutoff個股往返；產品契約由[個股頁 §26](STOCK_RESEARCH_PAGE.md#26-m2-focus-lots-1精確成交張數關注與同截止往返有限接受)負責。本輪API／UI服務以root此次held memory的preloaded Store運行，來源累計1 GET、runner新增0，stock／focus POST只再用cache；不是舊M1失效memory、fixture、磁碟copy或replay。Owned服務已結束、raw／receipt釋放，沒有新DB、raw檔或保存驗收；不擴市場／cutoff／歷史取得權限。

### 20.5 M2-FOCUS-DAY-MOVE-1 同來源的新觀測與方向 consumer

2026-10-06臺北本輪，root重新正面核dataset11370 metadata／OGL1.0、exact endpoint、有限本地用途與執行gate後，作唯一fresh GET200：`request_started_at=2026-10-06T00:05:01.697761+00:00`、`captured_at=2026-10-06T00:05:03.113904+00:00`。Body仍1,773,012B／12,060 data rows／18欄，SHA `bdfcead65b5c36d2bd75d20fe7b790fa56ce39d2547d0772989243550ca36149`；本次canonical `receipt_sha256=49f40ed7317d9af1d1a27c19d04a16dbe3ab1975dccee8e9e4d0914d0e5ae46a`。此為新取得觀測，不覆寫§20.2～20.4原UTC／receipt；§20.1的policy版本／digest、source_version、用途准入及body pins未變。

Root獨立核全結構、同日date-code唯一、兩股12金融欄、exact名稱／普通stock／TW-TPEx／TWD及原股→張。金融值與data ordinal仍同§20.2表，來源O/C原字串分別為3105的`614.00/615.00`、6488的`1220.00/1180.00`；不複製或修改舊金融表。資料日仍2026-10-05，10/06取得不代表今日即時行情、發布／首次可得、PIT或多日歷史。

方向consumer升版為 `price-lot-focus/m2-v2`，採同兩股／同截止原件的成交量及O/C給兩個可追溯理由；API、精確方向比較、去重及安全往返由[個股頁 §27](STOCK_RESEARCH_PAGE.md#27-m2-focus-day-move-1單日方向關注與完整條件往返有限接受)管理。Root在**同一程序**以本次held Store供真API／UI，來源累計1 GET、runner新增0；ordinary GET、focus POST2／stock POST2及條件變更同cache，無新外網。不借舊memory、fixture、disk copy或replay當actual。原件→API→具名操作與owned服務清理已接受；raw／receipt隨程序結束釋放，新增落盤0，保存／跨程序、全市場、歷史close／日曆及PIT未驗。

### 20.6 M2-FOCUS-TURNOVER-1 同來源的新觀測與成交額 consumer

2026-10-06臺北本輪，root正面重核Gov dataset11370 metadata200／exact href／OGL1.0、TPEx條款第5限制與第7政府資料例外，以及ISIN兩selected exact名稱、上櫃普通stock CFI `ESVUFR`。Wrapper沿TW／TPEx／stock／TWD／空ETF分類，金融單位為股、TWD元與元／股；source_version／§20.1 policy版本／1462B canonical digest／body pins均未變，worker仍 `tpex-price-capture/m1-v1`。用途、instrument與execution先核通，沒有以可讀endpoint或legacy collector外推准入。

唯一fresh exact GET200：`request_started_at=2026-10-06T04:34:40.994381+00:00`、`captured_at=2026-10-06T04:34:42.907564+00:00`；body1,773,012B／12,060 data rows／18欄，SHA `bdfcead65b5c36d2bd75d20fe7b790fa56ce39d2547d0772989243550ca36149`，canonical `receipt_sha256=8bc021810a3fbb148d60c02d112fd6516a491b4c0215d8543dc68d8c50aa6205`。Root獨立全結構、date-code唯一、兩股12金融欄及股→精確張／成交額核通，data ordinal205／717及唯一值依§20.2，不複製金融表。來源guards四項0；准入probe／編碼及assert原非零收據留原task，後正面准入與capture另核，原exit不改。

此為新觀測，不覆寫§20.2～20.5 UTC／receipt；資料日仍2026-10-05，不稱10/06今日行情、發布／首次可得、PIT或歷史close。Consumer升版 `price-lot-focus/m2-v3`，新增精確成交額條件與三理由，由[個股頁 §28](STOCK_RESEARCH_PAGE.md#28-m2-focus-turnover-1精確成交金額與四條件往返有限接受)管理，不擴source scope／金融表／用途。

Actual在同一程序以本次held Store供真API／UI，source累計1／runner新增0；ordinary GET、focus POST2／stock POST2與條件變更同cache，extra GET0。非舊memory、check fixture、disk copy或replay。原件→API→具名操作與owned清理已有限接受，raw／receipt隨程序結束釋放；落盤0，未驗保存／跨程序、全市場、歷史close／日曆及PIT。

### 20.7 M2-FOCUS-DAY-RANGE-1：新日期來源准入與本日振幅 consumer

本輪固定10/05 pins對fresh exact11370出現`price_body_version_mismatch`，不能機械換日期／hash。Root另核dataset11370 metadata／exact resource／OGL1.0、TPEx條款第5限制及第7政府資料例外、ISIN兩股exact名稱與普通stock CFI `ESVUFR`／上櫃市場後，才核新日期全結構、金融與版本；web provider403／timeout與direct200分報。ISIN初2MiB／Big5 probe exit1，後MS950／3MB selected strict pass；這些metadata／身分probe不是quote GET。

新policy `m1-price-tpex-11370-2026-10-06.1`，source_version `tpex-11370/2026-10-06`；以舊policy deepcopy只改version、scope.cutoff、新expected body SHA及attribution.release_version=`data-date-2026-10-06`。Canonical UTF-8仍1462B，digest `sha256:fc7b1451f6ae47145a5b40c3e08cdcad7ac8b9dafc64c7bf89f95c67cfefc288`；用途／exact URL／兩股／stock／TWD／process_memory及1 GET／3MiB／30秒／redirect0／retry0不變。原10/05完整policy／digest／body／金融表及§20.1～20.6收據保留；程式准入只限已明確核准10/05、10/06兩immutable tuples，不自動接新日。10/05 worker m1-v1保持，新10/06 builder／worker `tpex-price-capture/m1-v2`；memory projection版本仍m1-v1。

Root四次獨立quote觀測：old pins拒收、獨立old cutoff parser拒收、prospective script regex assert失敗、最後成功held新原件；前三rawexit1保留，不稱單一程序retry或一次成功capture。最後exact GET200：`request_started_at=2026-10-06T09:21:17.268510+00:00`、`captured_at=2026-10-06T09:21:22.201440+00:00`，body **1,788,599B／12,194 data rows／18欄**，ROC1151006、全date-code唯一。SHA `aae44dcb35107299a9f2cd47191301fe2cc2d980b6eae152927587df015bfd9a`。

此成功GET在m1-v2程式改動前由root取得並held；之後**同一程序**以新pure builder准入、獨立核全結構／原18欄／ordinal及下表12金融值，再供preloaded guarded runner。Canonical admitted receipt UTF-8 1408B，SHA `fe2c9513792df43378e0aa8e77c24a2f1f2d0baad8f47ff1c8716f6d7877d7dd`，新tuple／old digest不變核通。不能稱m1-v2原先發GET，也不能稱UI首次click觸發此次真GET；actual產品讀cached觀測，first-loader行為由synthetic另驗。長console命令曾被PTY截斷SyntaxError，body未失、短命令後核digest；原錯留task。

| 10/06 selected股／data ordinal／含header行號 | O／H／L／C原值（元／股） | 成交股數（canonical股） | 日常成交量（張） | 成交金額（TWD元） |
| --- | --- | --- | --- | --- |
| 3105穩懋／205／206 | 615.00／623.00／588.00／592.00 | 19731700 | 19,731.7 | 11863581093 |
| 6488環球晶／717／718 | 1175.00／1260.00／1145.00／1205.00 | 13913614 | 13,913.614 | 16835605385 |

兩股金融單位仍股、精確0.001張、TWD元及元／股；新表是來源版本實質變更，不覆寫10/05表。振幅分別精確`700/123`%及`460/47`%，O/C為down／up；產品精確門檻／四理由／五條件返回由[個股頁 §29](STOCK_RESEARCH_PAGE.md#29-m2-focus-day-range-1本日振幅與五條件往返)管理，不稱前日漲跌／ATR或策略。

Root actual API與UI render已有限核，preloaded Store source_request_count=1／runner新增GET0、server／client guards0、DB preserved=true；新source／policy／body經pure builder→Store→真router／render解除old pins阻擋，依賴增量dep+1。10/06不洩default／10/02／10/05；new pins服務不持有10/05歷史body。續驗可信桌面／窄版振幅與五條件同cutoff往返已由root有限接受，B1 core+1／dep+1／reliability0／stall0；最後額外invalid fallback native click未送達，不以tool ACK代操作。四owned pages已closed、兩owned RAM服務與compiler已停／listeners none，held原件memory於Python process absence釋放；服務shutdown rawexit1與清理後驗0分報，profile NO-RETRY殘留見[開發入口](development-baseline/README.md#m2-focus-day-range-1-新日期與五條件返回的記憶體驗證入口)。Raw／receipt只memory、無DB IDs／行情原件保存；資料日10/06不等於即時或精確發布／首次可得／修訂，後三unknown、PIT unsupported，不外推歷史close／日曆／全市場或磁碟保存。

## 21. M2-FOCUS-STOCK-SCOPE-1：三股來源准入

**新5347普通股身分、三股來源scope、計算、actual API與可信桌面／窄版往返已有限接受。** 支援TPEx3105穩懋、5347世界、6488環球晶，quote-date為2026-10-06；本輪臺北觀測日2026-10-07。本版由獨立新policy／body pins識別，不覆寫§20.1～20.7的兩股政策、金融表或收據。產品契約見[個股頁 §30](STOCK_RESEARCH_PAGE.md#30-m2-focus-stock-scope-1三股關注與同截止往返)。

### 21.1 身分、用途與獨立版本

Root正面核dataset11370免費／OGL1.0、[exact GET資源](https://www.tpex.org.tw/web/stock/aftertrading/DAILY_CLOSE_quotes/stk_quote_result.php?l=zh-tw&o=data)、當次TPEx網站條款第5自動下載限制及第7政府開放資料例外。沿§20.1的exact政府資源有限准入local_fetch／raw_store／summarize；只process memory、顯名、完整性、hash／版本／時間及traceability，不放行磁碟保存、legacy POST、附加歷史日期參數或其他URL。

ISIN當次資料日10/07正面確認5347世界、ISIN `TW0005347009`、掛牌日1998-03-25、上櫃／半導體業、普通股CFI `ESVUFR`；3105／6488原身分亦核一致。Wrapper明確TW／TPEx／stock／TWD、exact名稱及空ETF分類；混合quote不將其他證券猜作普通股，catalogue與selected scope須一致。ISIN／metadata日期不改行情quote-date。

新policy為 `m2-stock-scope-tpex-11370-2026-10-06.1`，canonical UTF-8 **1484B**，digest `sha256:6e662d5fc91957b586becdf41f351d5abf2c41cec09909de468e62e76cda4a78`。由§20.7舊10/06 policy只改policy version、symbols為3105／5347／6488及expected body SHA；attribution.release_version仍為 `data-date-2026-10-06`。Source version仍 `tpex-11370/2026-10-06`，須與完整scope、policy digest及body hash共同識別版本，不能只按日期選最新。

本版worker `tpex-price-capture/m2-stock-scope-v1`、projection `stock-price-memory/m2-stock-scope-v1`、consumer `price-lot-focus/m2-v5`。Default10/06選新三股tuple；explicit舊10/06 m1 policy與10/05兩股tuple保持immutable、各須自身pins。Policy選擇是內部設定，URL仍五條件，不新增第六個公開條件。每程序一次所選來源GET、body≤3MiB／deadline30秒／redirect0／retry0；普通GET、切股／條件與cached POST不新增外網，失敗不自動retry。

### 21.2 本輪觀測、原件與三股金融值

本輪有**兩次獨立root quote觀測**：首個非TTY程序成功後stdin EOF正常結束、原件memory釋放，只算source事實，不能聲稱供cached API／UI；第二個live程序取得並held原件，程式修改後在**同一程序**由pure builder准入並供actual API／UI。Store的source_request_count=1／runner新增GET0只描述第二個程序，不能當成本輪總GET只有1。

第二觀測 `request_started_at=2026-10-06T16:45:43.439089+00:00`、`captured_at=2026-10-06T16:45:45.945822+00:00`；body **1,788,599B／12,194 data rows／18欄**，ROC1151006、date-code唯一。Body SHA `ab34590df051d7ba08f35941811b69ee35f46c890212558b9f089119307b3200`；canonical admitted receipt **1433B**，SHA `a882859a0881860b13d2d77c0e39d78a25e4b078467a8b644256b4889696eed2`。Root獨立全結構、三股全部54個原欄字串、18個金融值及ordinal核通。日期仍10/06，但hash不同於§20.7的aae44…；未取得差異原因或修訂證據，不推論為官方revision或PIT。

| Selected股／data ordinal／含header行號 | O／H／L／C原字串（元／股） | 成交股數（canonical股） | 日常成交量（張） | 成交金額（TWD元） |
| --- | --- | --- | --- | --- |
| 3105穩懋／205／206 | 615.00／623.00／588.00／592.00 | 19731700 | 19,731.7 | 11863581093 |
| 5347世界／532／533 | 184.50／195.00／184.50／191.00 | 34637793 | 34,637.793 | 6615109776 |
| 6488環球晶／717／718 | 1175.00／1260.00／1145.00／1205.00 | 13913614 | 13,913.614 | 16835605385 |

金融單位仍canonical股、精確0.001張、TWD元與元／股；5347本日振幅精確為 `700/123`%，O/C為up。Raw54字串供來源詳情，不將讀欄數當全市場金融coverage。其他兩股價格／成交值與§20.7相同也不能推定整份body未變。

### 21.3 使用、驗收與剩餘邊界

Root在第二程序的preloaded Store驗三股同tuple／provenance、all3完整reads後filter、cached focus POST與三股stock POST；source Store1／runnerGET0、DB preserved=true、server／client guards0。Samecutoff具名可信桌面／窄版操作及owned清理已有限接受，core+1／selected identity-source scope dependency+1／reliability0／stall0；數值及操作由[個股頁 §30](STOCK_RESEARCH_PAGE.md#30-m2-focus-stock-scope-1三股關注與同截止往返)負責，入口與資源由[開發文件](development-baseline/README.md#m2-focus-stock-scope-1-三股範圍的記憶體驗證入口)負責，不將pure builder後讀cache說成首次UI click發fresh GET。

兩次觀測的原件memory現均已釋放，raw／receipt未落盤、DB IDs仍null。Quote-date不等於即時、published／first available／revision time；後三仍unknown，historical_pit unsupported。未驗磁碟保存／跨程序、20／21個股歷史close／完整calendar、strategy inputs／time／execution、MA／trend／研究／Signal／Plan或完整M1／M2／M3；範圍外標的／日期另須新正面准入。

## 22. M1-CLOSE-RESOURCE-1：有界單日 JSON 觀測

**M1-CLOSE-RESOURCE-1-OBSERVE-1 已由統籌有限接受；只接受指定 endpoint 的單份實際 body 觀測，沒有解除多日研究依賴或新增產品操作。** 官方 [dataset17257「上櫃歷史個股市值排行」](https://data.gov.tw/dataset/17257) metadata 為免費、OGL 1.0、每日更新的線索；前輪 [TPEx Swagger](https://www.tpex.org.tw/openapi/swagger.json) 476923B、SHA256 `05af7755d0d528626c104f7a8ccd7b00c6a0cf228d30bcb4669020e514eb0c7e` 記載 server `https://www.tpex.org.tw/openapi/v1`、exact GET `/tpex_daily_market_value`、parameters=[]。名稱含「歷史」與每日更新都不證 20／21 日可取窗口。用途與執行核定只涵蓋本次 exact 免費公開資源的有界本地記憶體觀測；不沿用 dataset11370 的 policy／pins，不增加 registry default、日期參數、legacy POST 或其他自動取得路徑。

Root 實際只作 1 GET：`https://www.tpex.org.tw/openapi/v1/tpex_daily_market_value`，無參數、redirect0／retry0、timeout20秒、raw≤3MiB、parsed≤24MiB、disk0。`request_started_at=2026-10-06T18:02:26.378163+00:00`、`captured_at=2026-10-06T18:02:26.446163+00:00`；HTTP200、Content-Type `application/json`、body137622B、SHA256 `612a0a516be4ac2f0a902a55a8911c0039b93ed592d9cadd60202e36ceddb61c`。Parsed object estimate870827B 只為本次物件估計，不是 RSS 或程序峰值；原件未落盤，owned 程序正常結束 exit0 後已釋放。

返回 890 rows／890 unique codes、無重複代碼；datecount1，全部 `Date=1151006`，只支持該 body 的2026-10-06資料日。實際七欄為 `Capitals`、`ClosePrice`、`CompanyName`、`Date`、`MarketValue`、`Rank`、`SecuritiesCompanyCode`；與政府 metadata 的 `StockPerShare`／`Close` 名稱不一致，不默認等義、單位或排序權威。三既有 symbol 的 close 與已驗10/06資料相符，但5347的 JSON `CompanyName=世界先進` 不等於 quote policy 的 exact name「世界」，不能自動擴 scope／換 pins。未核實全部890個 instrument 為普通股，MarketValue／Capitals 單位與 Rank 的產品用途未准入。

此單日 body **不是 20／21 日個股歷史 close 或完整交易日曆**；publication／first availability／revision lineage／PIT、strategy inputs、membership、decision／execution time 與所採合法執行條件仍缺。HTTP Date／Last-Modified／ETag 僅為回應 metadata，不改寫成資料發布或首次可得時間。不追加第二次取得、猜日期參數或宣稱全域無可行來源；本有限結論只適用這次 exact observation。

統籌依此單日結果改選獨立正面核心M2-FOCUS-STOCK-SCOPE-2-B1，四股操作後續已按[§23](#23-m2-focus-stock-scope-2四股來源准入)有限接受；本節只管理M1 observation，仍core0／dep0、不計implementation batch，沒有解除20／21close／完整calendar及strategy／time／execution。下一歷史資源須新正面query metadata／用途與執行核定，不重做本parameterless endpoint；工作與完成條件見[執行清單](ROADMAP_EXECUTION.md#21-近期里程碑接線映射)。

## 23. M2-FOCUS-STOCK-SCOPE-2：四股來源准入

**普通TPEx支援3→4、四股計算／actual API及可信桌面／窄版往返已由root有限接受。** 新增5274信驊，與3105穩懋／5347世界／6488環球晶使用同一2026-10-06 quote-date。該版source13＋DOC8 freeze21／qualified索引／exact commit與正常ff-only master merge `899fa62260e495075cc756ff31869a57df6b3895` 已接受；後續五股版本見§25，現行六股見§27。來源值及版本由本節管理，操作由[個股頁 §31](STOCK_RESEARCH_PAGE.md#31-m2-focus-stock-scope-2四股關注與同截止往返)管理；§20～21保留原兩股／三股immutable tuples、金融值與觀測，不覆寫舊policy。

### 23.1 身分、用途與獨立四股版本

Root fresh官方ISIN catalogue資料日2026-10-07、2983574B、SHA256 `68bc970ecc575e36a7820623d21691c44ca0a8d9d2d694dc021518a4e4fee71b`，正面核5274信驊、ISIN `TW0005274005`、掛牌日2013-04-30、TPEx／半導體業、普通股CFI `ESVUFR`。Wrapper仍逐股核TW／TPEx／stock／TWD、exact known name與空ETF分類；混合quote或890列JSON不能代普通股准入。Catalogue觀測日不改quote-date，也不補歷史membership／PIT。

Fresh [dataset11370「上櫃股票行情」](https://data.gov.tw/dataset/11370) 的免費／OGL1.0／每日metadata及[TPEx條款](https://www.tpex.org.tw/zh-tw/gtsm_disclaimer.html?l=zh-tw)第7點政府開放平台例外已重核；僅沿§20.1的 [exact CSV GET](https://www.tpex.org.tw/web/stock/aftertrading/DAILY_CLOSE_quotes/stk_quote_result.php?l=zh-tw&o=data) 有限local_fetch／raw_store／summarize用途與顯名、完整性、hash／version／time及traceability條件。只process memory，未授權磁碟保存、附加歷史日期參數、legacy POST或其他自動下載。

New policy `m2-stock-scope-tpex-11370-2026-10-06.2`、canonical UTF-8 **1500B**、digest `sha256:eb378f12e85462855d8271f1e977e4e84878882dd0944c004840a2ad21ab4434`，default10/06 scope依code為3105／5274／5347／6488。Worker `tpex-price-capture/m2-stock-scope-v2`、projection `stock-price-memory/m2-stock-scope-v2`、consumer `price-lot-focus/m2-v6`。Explicit `.1` 三股及更早10/06、10/05兩股tuple保持自身immutable pins／scope；policy選擇仍是內部設定，公開URL只有原五條件，不加入第六條。每程序一次合法明示取得、3MiB／30秒／redirect0／retry0與普通GET／cache零新增外網的既有條件保持。

### 23.2 Fresh原件、四股逐欄核對與5274金融值

Root owned同一程序在程式修改前先作唯一new CSV GET並held raw，修改後在同PID以pure builder准入新policy，再供preloaded actual API／UI；不是UI首次POST另作fresh GET。`request_started_at=2026-10-06T18:09:03.677364Z`、`captured_at=2026-10-06T18:09:04.958683Z`，HTTP200、body **1788599B／12194 data rows／18欄**、ROC1151006；SHA256 `ab34590df051d7ba08f35941811b69ee35f46c890212558b9f089119307b3200`。此為獨立fresh觀測，即使SHA與§21相同也不改寫為沿用舊memory或官方修訂證據。新admitted receipt **1440B**、SHA256 `3f4811496ab892e2dc3f88f78ed8f642839c206d8767fbf2b126d1a55ded8059`。

Root四股18欄逐欄核對：身分前三欄去除外側空白後一致，其餘60欄原字串一致；24個金融值一致。Worker／API `source_fields` 保留原名稱外側空白，5274原CSV名稱為 ` 信驊`，raw body未改；不稱72欄byte-equal或全市場金融coverage。既有三股金融值仍見§21.2，新股如下：

| Selected股／data ordinal／含header行號 | O／H／L／C原字串（元／股） | 成交股數（canonical股） | 日常成交量（張） | 成交金額（TWD元） |
| --- | --- | --- | --- | --- |
| 5274信驊／513／514 | 19520.00／19895.00／18855.00／18985.00 | 188693 | 188.693 | 3627465565 |

5274 O/C為down，本日振幅精確 `325/61`%；精確張、TWD整數元與原價比較沿穩定契約，不以「約」顯示值作門檻。API／可信往返、真零與缺資料界線見[個股頁 §31](STOCK_RESEARCH_PAGE.md#31-m2-focus-stock-scope-2四股關注與同截止往返)。

### 23.3 有限接受與剩餘邊界

Root accepted四股完整reads／同tuple／provenance、四理由去重、精確inclusive門檻、cached五POST及samecutoff五條件往返；preloaded Store sourcecount1／runner新增GET0、guards0、DB preserved=true。具名desktop／窄版操作與owned清理已接受，B1 coreoperation+1／selected identity-source scope dependency+1／reliability0／stall0；M1 §22 observation仍core0／dep0，不計implementation batch。

本輪唯一page已closed／tabs0、API／preview／compiler absent、8801／8802 listeners none；held raw已釋放，未落盤／DB IDs null。Raw terminal interrupt exit1與獨立清理後驗exit0分報，詳見[開發入口](development-baseline/README.md#m2-focus-stock-scope-2-四股範圍的記憶體驗證入口)與原task。Quote-date不等於published／first available／revision；後三仍unknown，historical_pit unsupported。未驗磁碟保存／跨程序、20／21歷史個股close／完整calendar、strategy inputs／membership／time／execution、MA／trend／研究／Signal／Plan或完整M1／M2／M3。下一來源或scope另需正面准入，見[ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑)。

## 24. M1-HISTORY-QUERY-1：官方月查詢線索與准入缺口

`M1-HISTORY-QUERY-1-METADATA-1`已接受有限只讀review，沒有歷史金融body、API／UI或核心依賴解除。官方[首頁](https://www.tpex.org.tw/zh-tw/index.html)導向[個股日成交資訊](https://www.tpex.org.tw/zh-tw/mainboard/trading/info/stock-pricing.html)；該primary HTML於2026-10-06T19:13:45.888930Z→19:13:46.064929Z GET200、12078B，SHA256 `a8a205fcdc43ced8ce2b329c3f8cb10240752633a4ac9916704c67d0785e9823`。這是metadata取得時間，不能推成歷史行情availability。

頁面inline action為 `afterTrading/tradingStock`；表單欄名 `code`／`date`，其中 `code` required、date-format M（`data-format=M`）、start19940101，列html／csv／utf-8匯出選項。Primary [main.js](https://www.tpex.org.tw/rsrc/js/main.js)的 `API_PATTERN=/www/{LANG}/{ACTION}`／lang=zh-tw與[tables.js](https://www.tpex.org.tw/rsrc/js/tables.js)的serializedForm／export GET支援這個NEW查詢線索；不將既有legacy `dailyQuotes` collector當官方query准入。

**仍未准入exact M月參數wire encoding與exact歷史自動使用權。** Dataset11371 metadata已取得，但extractor輸出截斷、resource LINK未准入；未再GET或造fallback證據。頁面與export GET方法線索不放行猜日期／參數、legacy POST或歷史body取得；11370當日CSV的用途也不自動擴張到月查詢。歷史金融body GET0，未解除普通股20／21真close、完整calendar及strategy／membership／time／execution；core0／dep0、不是implementation batch，stall0保持，不作全域不可能主張。

下一 `M1-HISTORY-MONTH-WIRE-1`須在原task核primary exact月wire／source-use／時間版本／instrument／execution，另核bounded memory、一次HTTP／timeout／redirect0／retry0／disk0，再作金融觀測。必要缺口仍缺時依[ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑)選獨立正面核心；命令、JS版本及原失敗留原task，不建立新附件。

## 25. M2-FOCUS-STOCK-SCOPE-3：五股來源准入

本節五股版本已合併至本輪starting master；當時pending由原task／Git final receipt覆蓋，現行六股另見§27，舊policy／金融與觀測不覆寫。

**普通TPEx支援4→5的來源／計算、actual API與可信桌面／窄版操作已由root有限接受。** 新增3293鈊象，selected依code為3105／3293／5274／5347／6488，quote-date仍2026-10-06。§20～23保留原兩股／三股／四股policy、金融表及觀測；具名操作由[個股頁 §32](STOCK_RESEARCH_PAGE.md#32-m2-focus-stock-scope-3五股關注與同截止往返)管理。

### 25.1 普通股身分、用途與獨立版本

Root本輪NEW官方ISIN catalogue GET：2983574B、SHA256 `68bc970ecc575e36a7820623d21691c44ca0a8d9d2d694dc021518a4e4fee71b`，逐股核普通TPEx／stock／TWD。新增3293鈊象、ISIN `TW0003293007`、掛牌日2006-07-12、上櫃文化創意業、CFI `ESVUFR`、ETF分類空；known name／code／身分須全合格。Catalogue日期與同hash新觀測不補歷史membership或PIT。

Fresh [dataset11370](https://data.gov.tw/dataset/11370)免費／OGL1.0與[TPEx條款](https://www.tpex.org.tw/zh-tw/gtsm_disclaimer.html?l=zh-tw)第7點政府開放平台例外已核；僅沿§20.1 [exact政府CSV資源GET](https://www.tpex.org.tw/web/stock/aftertrading/DAILY_CLOSE_quotes/stk_quote_result.php?l=zh-tw&o=data)的有限local_fetch／raw_store／summarize、顯名／完整性／hash／version／time／traceability條件。Metadata528827B、license484470B、disclaimer13535B的版本與full receipts留原task；當日用途不放行歷史日期參數、其他自動下載或磁碟保存。

New policy `m2-stock-scope-tpex-11370-2026-10-06.3`，canonical UTF-8 **1516B**、digest `sha256:57fb2dd808d71d43e89aca3fb42ef8dc53d9338093dd92a296858e62c41152ca`。Worker `tpex-price-capture/m2-stock-scope-v3`、projection `stock-price-memory/m2-stock-scope-v3`、focus `price-lot-focus/m2-v7`；default10/06採五股 `.3`，explicit舊 `.2`四股／m2-v6、`.1`三股／m2-v5、更早10/06兩股／m2-v4及10/05tuples保持自身immutable字典／pins／scope。公開URL仍原五條件，沒有第六條或新的automatic pins；每合法程序一次明示取得、30秒／3MiB／redirect0／retry0／disk0保持。

### 25.2 三次行情觀測與final actual原件

**本輪金融行情CSV GET總共3次，不是全輪一次。** OBSERVE-1因root預期名稱誤用U+9210、正確應為U+920A而assert失敗，raw釋放、exit1，未准入金融。OBSERVE-2新fresh body的金融核對／pure admit成功，但root自製outer network audit未含Windows loopback socketpair情境，API startup `network_denied1`、無8801 listener；structured helper stopped／DB preserved，不把此guard失敗改為全0。Root以stdlib獨立重現後，exact PID30296 Stop-Process exit0、absence／ports後驗0、raw隨process exit釋放，未transfer／export／replay。

OBSERVE-3用既有guarded actual API／live-source-opt-in與新pins，PID36908；trusted UI首次load button觸發一個NEW worker GET，sourcecount1／runnerGET1／preloaded=false。`request_started_at=2026-10-06T19:44:48.018375Z`、`captured_at=2026-10-06T19:44:48.918374Z`，HTTP200、**1788599B／12194 data rows／18欄／全1151006**；body SHA256 `ab34590df051d7ba08f35941811b69ee35f46c890212558b9f089119307b3200`。Admitted receipt **1447B**、SHA256 `e5e16747fd593b0014e3c6b3ca56b2e2f60876e2cad708904e519fb746120879`。Final actual body於程式修改後取得，與OBS2 fullbody SHA相同供獨立核對；不稱PID30296同程序preedit capture或final preloaded，沒有body copy／fixture替代。三次皆有原task明確授權，不是retry loop。

Root核selected五股共90欄：身分15欄去除外側空白比對，其餘75原字串exact；30金融值核實，raw／source_fields保留原名稱空白與追溯。新增金融值如下，其餘四股按§21～23原表沿用：

| Selected股／data ordinal／含header行號 | O／H／L／C原字串（元／股） | 成交股數（canonical股） | 日常成交量（張） | 成交金額（TWD元） |
| --- | --- | --- | --- | --- |
| 3293鈊象／255／256 | 794.00／794.00／772.00／780.00 | 1495462 | 1495.462 | 1164617657 |

3293 O/C為down，本日振幅精確 `1100/397`%；精確張、TWD整數元及原價比較沿穩定契約，不以「約」顯示值篩選。OBS2 parsed graph estimate4165915B低於24MiB，不是RSS；raw及receipt只memory，owned process結束後已釋放，DB IDs null。

### 25.3 有限接受與剩餘邊界

五股全部reads／同tuple／provenance先gate後filter，四理由去重／code順與safe五原字串保持。Root actual API10案、六cached POST零追加GET、同cutoff3293／可信桌面與窄版往返、真零及五股恢復已核；final guarded runner DB preserved／guards0。有效來源及產品驗收不抹去兩個earlier observer的原exit與custom guard失敗。

B1 coreoperation+1／selected identity-source scope dependency+1／reliability0／stall0；BOOT／§24 metadata／DOC／index／Git不計implementation batch。Owned page／服務／compiler／observer清理已接受，rawexit1與後驗0由[開發入口](development-baseline/README.md#m2-focus-stock-scope-3-五股範圍的記憶體驗證入口)分報。Quote-date不是published／first available／revision，後三仍unknown、historical_pit unsupported；未驗磁碟保存／跨程序、全市場、20／21歷史close／完整calendar／strategy time execution、MA／trend／ATR／研究／Signal／Plan或完整M1／M2／M3。

## 26. M1-HISTORY-MONTH-WIRE-1：月參數推論與用途缺口

`M1-HISTORY-MONTH-WIRE-1-DISCOVERY-1`已接受metadata review；core0／dep0、非implementation batch、不增加stall。§24保留前輪線索，本節記本輪NEW primary-script證據；沒有歷史月金融body、server acceptance、API／UI或20／21窗口依賴解除。

### 26.1 本輪primary metadata與wire推論

程式四次metadata GET均HTTP200、redirect0／retry0／POST0／financial0／disk0，合計328646B；原task先核max4 requests、各20秒／raw512KiB、總raw1MiB／parsed8MiB。UTC日期均2026-10-06；下表是取得版本，不是行情發布／availability。

| Primary resource | request→capture UTC | Bytes／SHA256 |
| --- | --- | --- |
| [stock-pricing HTML](https://www.tpex.org.tw/zh-tw/mainboard/trading/info/stock-pricing.html) | 20:29:32.919174→20:29:33.169323 | 12078／`78b6a66a647834827b53a9c323241a546c338d7e92d6c6fca688218189cfe674` |
| [actual loaded global.js](https://www.tpex.org.tw/rsrc/asset/js/global.js) | 20:29:54.783227→20:29:55.028391 | 103202／`58c3d641bde9aa9c6698ba6145df2a85257ee51f56dc263408a0518e1603e167` |
| [main.js](https://www.tpex.org.tw/rsrc/js/main.js) | 20:30:47.206703→20:30:47.373705 | 45227／`cfbd8c64c748149f039f1d4f1c5b3ba4511039b9c9e60d8ed53fd9624edc587a` |
| [tables.js](https://www.tpex.org.tw/rsrc/js/tables.js) | 20:31:41.599492→20:31:41.955655 | 168139／`085fd65b4e15e2af4f3adb3f256f0058d0176dd2d98ce53217ede16667a04a90` |

HTML的required code／date-format M／start19940101與action `afterTrading/tradingStock`、main的 `/www/{LANG}/{ACTION}`／zh-tw，指向 `/www/zh-tw/afterTrading/tradingStock`。Tables的#day.ymd `yyyy/mm/dd`、M初始化當月1日、Gregorian year/month→`new Date(year,month-1,1)`與data-value／.val設定，再由URLSearchParams append／toString及data-value override序列化，支持**Gregorian `YYYY/MM/01`→`YYYY%2FMM%2F01`的script推論**。大小寫M的UI月格式與main Date format的lower-m月份／upper-M分鐘分開；global.js選定literal search0不是窮盡不存在證明。

Tables提供export GET（serializedForm＋response=button format），一般JSON query則用`$.post`／response=json。這是primary code中的方法證據，沒有執行月GET／POST或確認server接受、金融日期範圍／完整性；不由推論放行猜參數或legacy collector。

### 26.2 用途仍缺與下一條正面路徑

Root另取[TPEx條款](https://www.tpex.org.tw/zh-tw/gtsm_disclaimer.html?l=zh-tw)與[OGL1.0](https://data.gov.tw/license)：HTTP200、14834B／484470B，SHA分別`2ecc3701beff3bfa6dc9a5fa80cb05c7ef9703b1cdb44e5d0e260465f127c0e3`／`d1e4856d8180be94478aee17d4d340796a1fae6f3bda4e2d7a0d3cda00e8902e`；UTC20:31:07.120994→20:31:07.273200、20:31:07.274200→20:31:07.511201。條款第5點同意方式／consent與第7點政府開放平台例外、顯名／完整性條件分開；§27 exact11370准入不等於歷史月資源自動使用權。Web工具先403與root actual GET200分報，不推成禁止或全域不可能。

Exact historical resource政府開放平台linkage／automated-use eligibility、時間版本／完整calendar與strategy／membership／time／execution仍未准入；metadata已釋放、歷史金融GET／POST0。下一優先`M1-HISTORY-OPEN-DATA-LINK-1`須找NEW primary linkage；不以同一失敗extractor重GET11371、不猜params／POST／legacy、不重複parameterless17257。Exact next resource／query／symbol／date／policy未准入；原task先核bounded memory／timeout／redirect0／retry0／disk0，再金融觀測。只有actual20／21普通股close＋complete calendar＋strategy／time／execution才算解除；無新可執行路徑時依[ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑)重選獨立正面核心。

## 27. M2-FOCUS-STOCK-SCOPE-4：六股來源准入

**普通TPEx支援5→6的來源／計算、actual API與可信桌面／窄版操作已由root有限接受。** 新增8069元太，code順3105／3293／5274／5347／6488／8069，quote-date2026-10-06；§20～25保留舊policy、金融表及觀測，現行操作見[個股頁 §33](STOCK_RESEARCH_PAGE.md#33-m2-focus-stock-scope-4六股關注與同截止往返)。

### 27.1 身分、用途與獨立六股版本

本輪NEW [ISIN catalogue](https://isin.twse.com.tw/isin/C_public.jsp?strMode=4)於2026-10-06T20:35:40.422739Z→20:35:42.754148Z GET200、2983574B、strict ms950；SHA256 `68bc970ecc575e36a7820623d21691c44ca0a8d9d2d694dc021518a4e4fee71b`。新增8069元太／ISIN `TW0008069006`／掛牌2004-03-30／上櫃光電業／CFI `ESVUFR`／ETF分類空；root逐股核全六股TW／TPEx／stock／TWD與known name／code。Catalogue同hash新觀測不補歷史membership或PIT。

Fresh [dataset11370](https://data.gov.tw/dataset/11370)於20:35:43.900148Z→20:35:44.463523Z GET200、528827B，SHA256 `9704cde685298de7d79224d1f5f61dd716343819d71e6ba8de41ae869f06caf3`；primary structured contentUrl為[exact免費政府CSV](https://www.tpex.org.tw/web/stock/aftertrading/DAILY_CLOSE_quotes/stk_quote_result.php?l=zh-tw&o=data)。頁面每日收盤後／stocks-ETF-ETN feed與selected普通股scope分開。沿OGL1.0及§26.2本輪條款第7點例外，僅准入此exact資源的bounded memory local_fetch／raw_store／summarize；顯名／完整性／hash／version／time／traceability保持，未放行月歷史參數、其他自動下載或磁碟保存。

New policy `m2-stock-scope-tpex-11370-2026-10-06.4`，canonical UTF-8 **1532B**，digest `sha256:03738997b4d8ec27872c58cfedef75c602aa17251b4a7724d1a375b6b85d8afc`。Worker `tpex-price-capture/m2-stock-scope-v4`、projection `stock-price-memory/m2-stock-scope-v4`、focus `price-lot-focus/m2-v8`；default10/06採六股，explicit舊`.3`五股／m2-v7、`.2`四股／m2-v6、`.1`三股／m2-v5與更早兩股tuples／pins／scope保持。既有10/06兩股backend producer=m2-v5，而frontend legacy consumer接受m2-v4相容；本輪未重寫舊producer。原五URL條件不變，每合法程序一次明示取得、30秒／3MiB／redirect0／retry0／disk0。

### 27.2 三次行情GET、final actual原件與金融值

**本輪金融CSV GET總3次。** OBS1在已GET後因root optional Content-Length diagnostic失敗，raw釋放、未准入；OBS2 root fresh held金融核對接受後釋放。OBS3是source修改後actual API PID38684的native首次load觸發一個NEW worker GET，sourcecount1／runner1／preloaded=false，沒有OBS2 preload／copy／replay；每次另經原task核定，不是retry loop。

Final `request_started_at=2026-10-06T20:53:02.476437Z`、`captured_at=2026-10-06T20:53:03.297160Z`，HTTP200、**1788599B／12194 data rows／18欄／全1151006**，quote-date10/06；body SHA256 `ab34590df051d7ba08f35941811b69ee35f46c890212558b9f089119307b3200`，等於本輪OBS2供root獨立核對。Admitted receipt **1454B**、SHA256 `b0400c6fb0a6b642c2c9bed39b88192c229b65921b6b5b9e3ec244825c33f47a`。Final guards0／disk0／DB preserved，raw／receipt只process memory、DB IDs null；服務清理後已釋放。

Root逐欄核selected六股108欄：18身分欄只去外側空白比對，其餘90原字串exact；36金融值、全部required reads／共cutoff與provenance已核。Raw／source_fields原名稱空白／追溯保持；新增金融值如下，其餘五股按§21～25原表沿用。

| Selected股／data ordinal／含header行號 | O／H／L／C原字串（元／股） | 成交股數（canonical股） | 日常成交量（張） | 成交金額（TWD元） |
| --- | --- | --- | --- | --- |
| 8069元太／12098／12099 | 147.00／151.50／145.00／149.00 | 10796741 | 10796.741 | 1607943663 |

8069 O/C為up，本日振幅精確`650/147`%；inclusive張／整數元／振幅用原exact值，不以「約」顯示值篩選。Quote-date不是published／first available／revision；後三unknown、historical_pit unsupported。

### 27.3 有限接受與剩餘邊界

Root actual API10案、六stock POST＋一focus POST cached且無新增source、四理由去重／code順／全六股先gate後filter；8069 samecutoff五原字串raw往返、desktop1277×924／窄版390×844與真零／恢復已核。B1 coreoperation+1／selected ordinary identity-source-date-policy dependency+1／reliability0／stall0；BOOT／§26 metadata／DOC／index／Git非implementation batch。Necessary checks與rawexit1／cleanup verify0分報由[開發入口](development-baseline/README.md#m2-focus-stock-scope-4-六股範圍的記憶體驗證入口)管理。

未驗磁碟保存／跨程序、全市場／PIT、20／21歷史close／完整calendar／strategy time execution、MA／trend／ATR／研究／Signal／Plan或完整M1／M2／M3。六股source13＋DOC8／freeze21／qualified七分區索引、exact commit及正常ff-only local master merge已接受；後續統籌visible gate亦已接受，收據留原task／協作紀錄。其他來源與scope不由本節自動准入。

## 28. M1-HISTORY-OPEN-DATA-LINK-1：開放平台metadata與歷史用途缺口

本輪三份完整native metadata body已有限review；歷史金融GET／POST0、core0／dep0、非implementation batch、stall0保持。§26月wire仍僅script推論，以下證據未建立exact月資源open-platform linkage／automated-use eligibility，不作全域禁止或歷史來源不可能主張。

### 28.1 Exact REST／SSR版本及觀測邊界

官方rendered [dataset介面說明](https://data.gov.tw/about/doc?chapter=27&doc=8)與[suggests介面說明](https://data.gov.tw/about/doc?chapter=76&doc=13)支持GET `/{datasetId}`／`/{suggestId}`、無query的REST wire；rendered指南不是native body receipt。Root首次native guide GET在1MiB／20秒raw／deadline assertion失敗、exit1，未取得可准入完整body／hash，raw已釋放，未自動retry。

| Native metadata／HTTP200完整body | request→capture UTC（2026-10-06） | Bytes／SHA256 |
| --- | --- | --- |
| [REST dataset11371](https://data.gov.tw/api/v2/rest/dataset/11371) | 21:47:46.801710→21:47:47.016911 | 3128／`600e7a88bce62c4594ff51a7785bc47442013e29dac33329a2d6af9227dd1002` |
| [suggest136936 SSR](https://data.gov.tw/suggests/136936) | 21:50:22.892381→21:50:23.292382 | 473658／`5bf70f34d43a687a5b85677ac55802a63afccb836645a74cfa75140fe336269a` |
| [REST suggest136936](https://data.gov.tw/api/v2/rest/suggests/136936) | 21:52:46.630982→21:52:46.793982 | 3090／`bf16525d2b8f5d6e56ecdc6d5cce68f86b1f0f84d74df0f8c6fccd0b116cd984` |

三次各先核one GET／20秒／raw1MiB／parsed8MiB、redirect0／retry0／disk0，完整body合計479876B；parsed graph estimates分別12381／1429333／6870B，不是RSS。每次process結束釋放，沒有附件、原件保存或金融驗證。

11371標題上櫃股票收盤行情，identifier `A45020000D-000079`、published2015-12-03／modified2024-12-05 09:28:05；免費／license1、每日收盤後stocks／warrants／ETF／ETN，唯一UTF-8 CSV為[exact daily resource](https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php?l=zh-tw&se=EW&o=data)。16欄、method／OAS空、request path parameters=[]；quality2026-08-19 17:15:25及resourceAmount934不等於金融body核對、歷史coverage或月alias。

### 28.2 Reply history、身份未證與剩餘缺口

SSR題名為上市與上櫃個股日成交資訊歷史查詢，顯示FSC分派／已回覆；此SSR未見agency reply文字、TPEx／TWSE外部anchor為空，僅是該surface邊界。完整REST另有reply history，不由SSR空白推成沒有回覆。

REST top comment554663／pid0／2025-01-24 17:02:27稱歷史資料提供販售、政府平台只提供最新資料，連到TWSE／TPEx e-shop並帶「證交所及櫃買中心謹復」署名。suggest_type無法開放／reply_status已回復／status已結案(未開放)、notopen_reason無資料，尚未蒐集建置；open_datasetID／application_url空。這不提供免費exact月alias或自動用途准入。

Nested554664／pid554663詢問每天更新及自行累積歷史，是提問而非授權。Nested554666／pid554664／2025-02-13 13:51:42回覆約交易日下午2點每天更新並引OGL1.0無需額外書面許可的權利；只支持latest每日收集邊界，不補成archive／月資源grant。Top masked author `z****6`、nested作者role未提供，top comment subject實為信用卡特約商店分類與帳務資料，與主題不符；帳號身份仍unverified，不能把署名當獨立官方帳號證明。

Exact歷史月資源linkage／用途仍缺，actual20／21普通股close＋complete calendar＋strategy／time／execution未解除。Root據新證據重選§29獨立正面核心；無新可執行歷史path時保留待驗，不反覆相同wire／extractor或legacy retry。

## 29. M2-FOCUS-STOCK-SCOPE-5：七股來源准入

普通TPEx支援6→7新增6510精測已由root有限接受，code順3105／3293／5274／5347／6488／6510／8069、quote-date2026-10-06；原六股canonical byte-equal。具名操作由[個股頁 §34](STOCK_RESEARCH_PAGE.md#34-m2-focus-stock-scope-5七股關注與同截止往返)管理，§20～27歷史版本保持。

### 29.1 Fresh身份／政府linkage與獨立版本

Root fresh [ISIN catalogue](https://isin.twse.com.tw/isin/C_public.jsp?strMode=4)於2026-10-06T21:56:55.796038Z→21:56:58.334663Z GET200、2983574B／strict ms950；SHA `68bc970ecc575e36a7820623d21691c44ca0a8d9d2d694dc021518a4e4fee71b`。6510精測／ISIN `TW0006510001`／掛牌2016-03-24／上櫃半導體業／CFI `ESVUFR`／ETF分類空；全七股TW／TPEx／stock／TWD已核。這是operational catalogue，不補歷史membership／PIT。

Fresh [REST dataset11370](https://data.gov.tw/api/v2/rest/dataset/11370)於21:56:58.521664Z→21:56:58.741663Z GET200、3184B，SHA `64950fc1b492ee223fe86e16fb7d49a27426d1697c0c1f4553330279ca09fbe4`，linkage為[exact政府daily CSV](https://www.tpex.org.tw/web/stock/aftertrading/DAILY_CLOSE_quotes/stk_quote_result.php?l=zh-tw&o=data)。同批fresh [OGL1.0](https://data.gov.tw/license)484470B／SHA `1155d5e33bfcf113a5554de7c27d60084244044ea0625f7f56c0280225b109ba`及[TPEx條款](https://www.tpex.org.tw/zh-tw/gtsm_disclaimer.html?l=zh-tw)14834B／SHA `74564ae8a0bb7dfe38c7dad17f13dd0bf3ca28ae40bcd813dffb81d53ce2d6b7`，均HTTP200；四metadata GET共3486062B、memory已釋放。沿政府平台例外／顯名完整性，僅准入此exact daily資源的bounded process-memory local_fetch／raw_store／summarize，不放行磁碟保存、歷史參數或其他自動下載。

New policy `m2-stock-scope-tpex-11370-2026-10-06.5` canonical UTF-8 1548B／digest `sha256:5e397d1e560860208e11c8877fe539f38701757f8ba48dc6e7fea8ef8c0c4040`；worker `tpex-price-capture/m2-stock-scope-v5`、projection `stock-price-memory/m2-stock-scope-v5`、focus `price-lot-focus/m2-v9`。Default10/06採七股；explicit舊`.4`六股及更早tuples／pins／scope immutable，舊兩股producer／consumer相容保持；原五URL條件不增第六條。

### 29.2 兩次金融GET與final actual原件

本輪financial CSV GET總2：OBS1 root獨立fresh於21:57:26.781009Z→21:57:27.625218Z、rawexit0後釋放；retained graph estimate5133807B≤32MiB，不是RSS。OBS2是source修改後actual API PID8752的native首次load觸發NEW worker GET，於22:11:43.161045Z→22:11:43.943046Z、Store1／runner1／preloaded=false，沒有OBS1 preload／copy／replay，不稱全輪只GET1。

Final HTTP200、1788599B／12194 data rows／18欄／全1151006，body SHA `ab34590df051d7ba08f35941811b69ee35f46c890212558b9f089119307b3200`與root OBS1相同。Admitted receipt1461B／SHA `3df8b33c7518b730ae21e89dd82ef4297ea0ed535dbe4cb1af8e2f0d005d4757`。Root核七股126欄：21身份欄只去外側空白比對，其餘105原字串exact、42金融值、全部required reads／cutoff／provenance合格；raw source_fields原空白保持。Guards0／disk0／DB preserved／DB IDs null，API exit後held raw已釋放。

| 新股／data ordinal／含header行 | O／H／L／C（元／股原字串） | canonical股 | 日常張 | 成交金額（TWD元） |
| --- | --- | --- | --- | --- |
| 6510精測／726／727 | 3125.00／3140.00／3050.00／3055.00 | 560518 | 560.518 | 1729347985 |

6510 O/C為down，本日振幅exact2.880%；比較沿穩定精確契約，不以顯示「約」或千分位替代原值。Quote-date不等於published／first availability／revision，後三仍unknown、historical_pit unsupported。

### 29.3 有限接受、進度及保存缺口

Source14／net27343B、actual API10案及可信desktop／窄版samecutoff往返已接受；coreoperation+1／selected identity-source-date-policy dependency+1／reliability0／stall0。BOOT／§28 metadata／DOC／index／Git不計implementation batch。必要checks與原exit／清理由[開發入口](development-baseline/README.md#m2-focus-stock-scope-5-七股範圍的記憶體驗證入口)管理；DOC review／freeze／qualified affected index／exact local commit／另准master merge尚待。

下一優先M1-PRICE-SAVE-1是PRIVATE local store保存已准入單日capture／provenance並跨程序讀回的產品操作；目前`.5`仍只process memory，新disk用途policy／schema／private path／files caps及清理尚未准入。新root須先核fresh source／storage-purpose／time／version及具體bounded原task範圍，再金融GET／落盤；完整body SHA讀回需one bounded raw＋canonical receipt，selected projection不足。須actual disk與cross-process API／UI驗收，不宣稱20／21close／calendar／strategy／execution或完整M1／M2／M3完成，亦不以ATR／Signal／Plan／ranking替代。

## 30. M1-PRICE-SAVE-1：私人單日保存與跨程序讀回

**TPEx七股／2026-10-06的完整原件保存、NEW process重驗、actual API及具名操作已由root有限接受。** Scope仍3105／3293／5274／5347／6488／6510／8069、ordinary stock／TWD；操作由[個股頁 §35](STOCK_RESEARCH_PAGE.md#35-m1-price-save-1私人單日保存與跨程序操作)管理。§29的`.5` process-memory capture／pins／金融值全留；新增獨立storage overlay，不改原capture事實。

### 30.1 Fresh用途與獨立storage版本

Root於2026-10-06T23:03:24.074791Z～23:03:24.687792Z fresh取得[REST11370](https://data.gov.tw/api/v2/rest/dataset/11370)3184B／SHA `64950fc1b492ee223fe86e16fb7d49a27426d1697c0c1f4553330279ca09fbe4`、[OGL1.0](https://data.gov.tw/license)484470B／SHA `f123f1949f22db90d61d8142051a91ab49b1887133c3d477648aec57256b3c9b`及[TPEx條款](https://www.tpex.org.tw/zh-tw/gtsm_disclaimer.html?l=zh-tw)14834B／SHA `ead63b3a74530eb996accdbf96c750e01769149c9d8a7622b6277855b79095d5`；三metadata GET共502488B、rawexit0／disk0。Exact政府daily CSV linkage不變；政府例外、local copy、署名與完整性支持有限私人保存，未准入普通股月歷史或任意自動下載。

Storage policy `m1-price-save-tpex-11370-2026-10-06.1` canonical UTF-8 2437B、digest `sha256:0e0d9f77fdfa97f2fe9864b9f1cfe2e73429899f1e0aea6c006c7630f0d7201e`；須同時核原`.5` capture pins及新storage pins。保存對象是已准入、完整可重驗的capture；原receipt仍`storage=process_memory`，不改寫成落盤capture。Storage receipt `tpex-price-storage-receipt/m1-v1`另記`storage=private_local`；projection為`stock-price-saved/m1-v1`。不自動變更default date／pins、fetch、hydrate或正式DB。

### 30.2 三檔、原子出版與嚴格重驗

唯一bundle literal files為`body.csv`、`capture-receipt.json`、`storage-receipt.json`。前兩者保持完整原body及原canonical receipt bytes；storage receipt exact schema含`version`／`storage`、storage/capture policy version＋digest、source identity/version／endpoint／GET／as_of／selected_symbols、body SHA/bytes、capture receipt SHA/bytes、request_started_at／captured_at／saved_at、attribution與limitations。Saved time須為aware UTC且不早於capture；它不是publication／first availability／revision。

先驗完整raw、canonical／schema／receipt／pins／來源日期與七股，再在exclusive staging建三檔並atomic rename至唯一final目錄。既有final須完整驗證；idempotent回傳既有bytes／saved_at，不覆寫或挑其他版。NEW process重開再驗完整body、兩份canonical receipt exact bytes及所有上述關係，不以selected projection替代fullbody hash；缺檔、部分bundle、污染／schema／pin／日期衝突均拒用，不較早fallback。API不以saved檔自動hydrate memory Store，原DB IDs仍null。

Windows private path保護目前只驗Windows；未提供其他平台保證。核定product root為`C:/Users/YiCheng/AppData/Local/taiwan-stock-research/price-save-01a11367`，final子目錄`tpex-11370-2026-10-06-m1-v1`；max one bundle／3files、raw≤3MiB、capture receipt≤8KiB、storage receipt≤16KiB、合計≤3170304B。測試quota、精確殘留及清理拒絕由[開發入口](development-baseline/README.md#m1-price-save-1-私人磁碟保存與新程序驗證入口)詳述；本准入不是其他scope的磁碟grant。

### 30.3 本輪兩次金融capture與actual保存

CURRENT round financial GET總2：OBS1 root獨立fresh於23:10:37.153166Z→23:10:38.119320Z，normal exit0後釋放／disk0；OBS2 post-source-edit producer PID29780的native首次load觸發NEW worker於23:32:17.666931Z→23:32:21.005311Z，Store1／runner1／preloaded=false，沒有OBS1 preload／copy。兩次capture分開記時，不稱全輪只GET1。

Final HTTP200、1788599B／12194 data rows／18欄／全1151006，body SHA `ab34590df051d7ba08f35941811b69ee35f46c890212558b9f089119307b3200`。23:32:45.499432Z native save actual三檔1791644B：body1788599B、原capture receipt1461B／SHA `871a6887a3b87bd7c23c20fc3a25ec98d369d0df2ed8eedbe8cb040e5242cd36`、storage receipt1584B／SHA `436465b4d13d604965327fe1be7eff98edf65274b0f16c7871474280feb0197b`。Root獨立核full raw結構、兩receipt canonical、126 source fields（21身份欄外側trim比對／105原字串exact）、42金融值與七one-based ordinals；6510 ordinal726／含header727。重按保存files／timestamp／write／source均不變。

Producer停止後NEW reader PID33208 empty Store／memory disabled／source0／preloaded=false；same三檔bytes/hash與all126／42 actual saved API已root接受，reads writes0／mutations0／guards0／DB preserved。Memory raw在程序停止釋放；磁碟body仍保留，不稱原件全刪。Observed／save時鐘不證publication／PIT。

### 30.4 有限接受及未驗

Source13／net70181B與必要checks已root接受；本B1 coreoperation+1／finite private-save source-use、fullraw＋canonical storage及NEW process dependency+1／reliability0／stall0。BOOT／DOC／index／Git不是implementation batch。Actual缺cutoff／10/05／10/07拒用、empty memory save拒用、reader capture POST405及具名API／UI邊界見個股頁§35。

產品三檔清理被automatic review在CreateProcess前以`blocked by policy`拒絕，未執行刪除、維持NO-RETRY；不否定有效功能驗收。Actual missing-file native UI未跑，corruption／schema／partial gate只具synthetic證據；actual失敗UI是connection/proxy502，不改稱missing-file驗收。完整M1／M2／M3、20／21普通股close／complete calendar／strategy time execution、全市場／PIT仍未完成。

## 31. M1-CHIPS-CUTOFF-1006-1：同10/06法人窗口與完整有界日曆

**新來源用途、完整24日曆、20真daily、兩股12 net／actual API及可信desktop／窄版已由root有限接受。** 僅TPEx3105穩懋／6488環球晶、explicit `as_of=2026-10-06`；原件為當次事後觀測、process memory，非PIT。§19 W8的3613B canonical／SHA `6a7e4aa786edf6ff801d411daeb254623ca9dce4815b771d51aa9a57e1da89cb`、截止10/02及worker／API pins immutable；舊六價格canonicals與default日期不自動提升。產品操作見[個股頁 §36](STOCK_RESEARCH_PAGE.md#36-m1-chips-cutoff-1006-1同截止法人窗口與完整日曆)。

### 31.1 Exact集合、用途與版本

新policy `m1-chips-cutoff-tpex-2026-10-06.1`，profile `free_public_local`；canonical UTF-8 **4264B**，外部 `policy_digest=sha256:36c761a5f6e22afee86ad414769b88c06e97ae792141879a5660cf0856c180d5`。完整policy／exact集合／用途／scope及digest須同時匹配，不能自行計算expected pin或沿用W8、global registry、單日price／private storage grant。

| Source ID／observed版本 | 准入GET資源與exact參數 |
| --- | --- |
| `tpex_government_index_csv`／`dataset-11391-month-csv-observed-2026-10-07/chips-v1` | [dataset11391](https://data.gov.tw/dataset/11391) exact [inx](https://www.tpex.org.tw/www/zh-tw/indexInfo/inx?response=data)，`date=2026/09/01`及`2026/10/01`（wire依URL encoding）；先驗全部返回月列。 |
| `tpex_government_institutional_csv`／`dataset-11856-dated-csv-observed-2026-10-07/chips-v1` | [dataset11856](https://data.gov.tw/dataset/11856) exact [dated daily](https://www.tpex.org.tw/web/stock/3insti/DAILY_TradE/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&o=data)，`d=115/MM/DD`只限下述20 required sessions。 |

Root先核REST兩dataset、[OGL1.0](https://data.gov.tw/license)、[TPEx條款](https://www.tpex.org.tw/zh-tw/gtsm_disclaimer.html?l=zh-tw)第7點政府開放資料例外、[平日交易規則](https://www.tpex.org.tw/zh-tw/mainboard/trading/rules/system.html)與[11503027221休市公告](https://www.tpex.org.tw/storage/eb_data/11509/11503027221.html)，共6 metadata GET／546788B、memory only／redirect0／retry0／disk0。第5點限制不因endpoint可讀而消失；新grant只准此集合的 `local_fetch/raw_store/summarize`，raw_store本輪只process memory，不授權磁碟／正式DB或任意自動下載。署名保留櫃買中心、兩dataset、OGL1.0及資料／觀測版本；publication、first availability、revision time／lineage與數字rate limit未知，`historical_pit=unsupported`。

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

### 31.4 獨立觀測、金融真值與完整性

本輪financial **TOTAL46 GET**：首次Sep probe1（root唯讀腳本錯把index日期當ROC而exit1，body bytes／SHA未記錄；不證來源width／contract failure）＋獨立Oct diagnostic1＋修正後ROOT OBS2 22＋post-source-edit native fresh22。Metadata6另計；兩個成功22批各2907099B，不是整輪22或同capture預載／重放。Known body bytes5814474＝2×2907099＋Oct diagnostic276，另有首次Sep probe unrecorded body；不能宣稱整輪total bytes完整。

OBS2與native均24 full index rows／18,098 full daily rows。Native producer13668為NEW empty新／W8 Stores、finance seed0、只有兩actual identities；trusted BUTTON前source0，首次22於UTC `2026-10-07T01:12:55.829688`～`01:13:15.496773`取得。Root獨立reader externalGET0／disk0／guards0，驗全部22 body bytes／SHA與原22 canonical capture receipt SHA（不對augmented provenance重算）、40原列1000原字串／880金融欄、144 calendar fields、全部ordinals及12 net。Native與OBS2全部22 body hash＋1000欄相等；reader value graph9568313B為估算非RSS／peak。19 DB表schema／values／每cell typeof前後相等。

唯一金融真值集中下表，順序外資（不含外資自營商）／投信／自營商，單位canonical股；日常UI依穩定張公式除1000、最多三位小數去尾零：

| 標的 | 5日net（9/30～10/6） | 20日net（9/7～10/6） |
| --- | --- | --- |
| 3105穩懋 | `[27460450, 2352400, 2227304]` | `[36689368, 17747988, 2886699]` |
| 6488環球晶 | `[594644, 1330929, -11515]` | `[-14155476, -553503, -367682]` |

### 31.5 有限接受與剩餘缺口

Core operation+1／必要source-use＋24 observed calendar＋true daily dependency+1／reliability0／stall0。Actual API／native及失敗清值界線見[個股頁 §36](STOCK_RESEARCH_PAGE.md#36-m1-chips-cutoff-1006-1同截止法人窗口與完整日曆)，測試／原exit及owned清理見[開發入口](development-baseline/README.md#m1-chips-cutoff-1006-1-同截止法人窗口的零落盤驗證入口)。本輪raw隨producer／reader正常退出釋放、diskartifact0，不改舊price私人三檔仍存在事實；新有限日曆不解除普通股20／21close、trend／strategy、PIT／time／execution、保存／跨程序或完整M1／M2／M3。

## 32. M1-SAVED-PRICE-FOCUS-1006-1：保存來源的七股關注准入

**七股／2026-10-06保存來源的四項條件篩選、actual API及同截止原生往返已由root有限接受。** 只含3105穩懋／3293鈊象／5274信驊／5347世界／6488環球晶／6510精測／8069元太，TW／TPEx ordinary stock／TWD，code升序。使用者操作由[個股頁 §37](STOCK_RESEARCH_PAGE.md#37-m1-saved-price-focus-1006-1保存來源關注與同截止往返)管理；§29 memory focus、§30私人保存及§31法人窗口各自保留原契約。

### 32.1 先准入只讀用途，再讀既有原件

本root在private read／implementation前於原task核定finite saved read-use。依§30已接受的政府例外、local private copy、署名與完整性，只准既有三檔的本機只讀重驗及有限衍生，不新增metadata／financial GET、複製、export／publish、hydrate、磁碟保存或正式DB用途。此准入不繼承未採來源的history／PIT／自動下載權，也不改default。

新consumer policy `m1-saved-price-focus-tpex-11370-2026-10-06.1` canonical UTF-8 **2677B**，外部digest `sha256:93059779e66d7826818db4a9eb9ea0a6856d631234b0efaa93c98241d6e5de3b`；projection `price-saved-focus/m1-v1`。須另核原capture `m2-stock-scope-tpex-11370-2026-10-06.5`／digest `sha256:5e397d1e560860208e11c8877fe539f38701757f8ba48dc6e7fea8ef8c0c4040`，及storage `m1-price-save-tpex-11370-2026-10-06.1`／digest `sha256:0e0d9f77fdfa97f2fe9864b9f1cfe2e73429899f1e0aea6c006c7630f0d7201e`。三種policy角色獨立；不把新consumer pins寫入原receipt或擴大七股scope。

唯一existing bundle為 `C:/Users/YiCheng/AppData/Local/taiwan-stock-research/price-save-01a11367/tpex-11370-2026-10-06-m1-v1/`。Literal三檔、原canonical schema／bytes／SHA及Windows path保護仍由§30.2～30.3管理；本輪重驗結果與該表完全相同。原capture `storage=process_memory`／`request_count=1`是歷史capture事實；當前來源另標 `origin=private_local`、storage receipt仍 `private_local`。Augmented provenance不當作原canonical receipt重算hash。

### 32.2 完整重驗與有限衍生

每次合法snapshot重新驗完整body、兩份**原canonical** receipt、全部三檔full hash、source identity／version／endpoint／method／日期／七symbols、capture/storage/consumer pins與時間關係；不以selected projection代替body hash。全12194 data rows／18欄header、global width、ROC1151006與date-code唯一性受驗；金融值只宣稱七股126 source fields／42金融值，原字串保持。

Capture UTC `2026-10-06T23:32:21.005311+00:00`、saved UTC `2026-10-06T23:32:45.499432+00:00`保持；不等於publication／first availability／revision，後三unknown、historical_pit unsupported。Body1788599B、capture receipt1461B、storage receipt1584B，共1791644B／3files；hash仍§30.3原值，所有mtimeNS不變。

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

### 32.3 實際讀取與可證上限

ROOT OBS1為pre-edit完整三檔讀取；OBS2為post-edit完整原件解析與獨立manual API核對；OBS3為normal停止後full SHA核對，共3bundle／9file reads。實際NEW readonly reader1 empty Store／preloaded=false／financeSeedRows0／memorydisabled，26成功snapshots；原task另准NEW reader2以相同空Store驗尚未驗的detail失敗分支，2成功snapshots。Total28在root兩程序共用96 quota內；implementation counter是各程序96，不可稱一個程序或把reset當成額外授權。實際snapshot logical file reads84＋獨立9＝93。

Current external financial GET **TOTAL0**、metadata GET0、new disk writes0／DB mutations0／audit0；原capture request_count1不計成本輪GET。每read 10s為read後與parse後的**cooperative檢查**，不是OS搶占或hard wall。單bundle／3files：raw≤3145728B、capture≤8192B、storage≤16384B、合計≤3170304B；retained graph≤32MiB為object graph估算，不是RSS／peak。本輪root observed graph1950700～2553056B。超限／不合schema／hash／pins／日期的拒用與不讀unsupported日期界線由§37管理。

### 32.4 有限接受與保存邊界

Source13／net84588B已獨立接受；coreoperation+1／necessary derived saved-source readonly-use dependency+1／reliability0／stall0。19 memory DB表的table/index/trigger定義、全部values及cell typeof在兩reader前後相等，guards全部0；無capture_attempt／cache／raw／DB hydration。必要checks與owned runtime清理分報，見[開發入口](development-baseline/README.md#m1-saved-price-focus-1006-1-保存來源關注的零落盤驗證入口)。DOC review→freeze→qualified affected index→exact commit→另准master merge仍待。

既有1791644B三檔仍在磁碟；私人清理的auto-review在CreateProcess前 `blocked by policy`，未啟動process／未刪除，STRICT NO-RETRY及at-cap禁新增diskcases保持。Actual missing-file UI未跑，完整性／schema等negative是必要synthetic memory證據；actual native失敗為HTTP502。不得稱global disk0、所有raw已釋放或磁碟清理成功。普通20／21close、trend／strategy／time／PIT／execution、全市場與完整M1／M2／M3仍未完成。

## 33. M1-SAVED-PRICE-CHIPS-INTEGRATION-1006-1：保存行情與法人窗口共同入口

**Saved-focus→3105／6488同10/06 saved OHLC＋真5／20net→追溯／五原條件back已有限接受。** NEW guarded API/preview解除原saved-only/chips准入缺口；co-render/duplicate capture不計核心。操作見[個股頁 §38](STOCK_RESEARCH_PAGE.md#38-m1-saved-price-chips-integration-1006-1共同入口與同截止往返)，§29～32保持。

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

Raw/capture/storage caps3145728/8192/16384B，bundle≤3170304B／one bundle。Shared64bundle/192file reads含ROOT，producer ceiling61＋ROOT3。Actual producer9（native6＋local API3）／ROOT3＝12/36，含首次Unicode assertion raw1；corrected OBS2／post-stop OBS3全bytes/SHA/mtimeNS通過。Entry/apply/switch/back無明示read則private0。

Price UTC2026-10-06 started23:32:17.666931／captured23:32:21.005311／saved23:32:45.499432；publication/first availability/revision unknown、PIT unsupported。Snapshot10s cooperative／graph32MiB，actual1950740/1950828B retained estimates，非OS硬deadline/RSS/peak。

### 33.3 Fresh金融集合/guards

只准SINGLE NEW empty producer／capture_attempt1，external metadataGET0、price financialGET0；trusted首次chips POST才取得§31 exact2 index＋20daily＝22 official GET。API與preview各自在upstream前限 `POST /api/stocks/TPEx/(3105|6488)/institutional-windows/capture?as_of=2026-10-06`；query一次，非空UTF8 body≤4096B且須空JSON物件，壞body/query422、oversize413、其他POST405。其他五股不capture；GET unknown/duplicate query先422，舊/prices/saved405，focus unsupported日期先unavailable/private0。UI核saved detail context／五RAW。

僅admitted chips network context准exact HTTP／TPEx443 DNS-connect，redirect/retry0；index≤1MiB、daily≤2MiB、aggregate≤42MiB、received header≤16KiB。Request min(15s, remaining budget)、batch180s在response／chunk邊界檢查；chips64MiB／joint96MiB retained graph估算。非OS硬wall、socket header搶占或RSS／peak。

Actual22＝2907099B；24index dates/144原欄、18098daily全列width/date/code唯一及40selected/1000原字串/880 canonical int64全驗。ROOT獨立核all22 body＋ORIGINAL canonical receipt SHA/times、12net同§31真值，fresh非replay。Capture UTC2026-10-07T04:19:33.546820～04:19:43.937624、10.391s cooperative；chips graph3273840B。歷史§31 financial46＋metadata6／§30price2／focus0依原輪分列。

啟動時NEW price/chips/W8 Stores空／finance seed0；19 SQLite full schema/values/cell typeof不變，guards0/new product disk0/DBmut0。Current private read、chips capture／stock read／refetch或provenance核對失敗，同時mask saved prices／chart／raw與nets／calendar／dailyraw，保留ONE diagnostic。恢復須same context／generation兩次成功：明示NEW private snapshot＋明示held institutional read；held不外網refetch。舊generation成功不unmask，failed capture不retry／restart，無有效held raw維持unavailable。ROOT-only memory diagnostics／held原body＋receipt不capture/snapshot或回HTTP private fullbody。

### 33.4 接受與殘留邊界

B1 coreoperation+1／necessary joint-source-use-guard dependency+1／reliability0／stall0；BOOT／DOC／index／Git不計核心。Actual same-token502清兩來源已接受，missing-private-file UI未跑；必要checks／原失敗及owned runtime退出見[開發入口](development-baseline/README.md#m1-saved-price-chips-integration-1006-1-共同入口的零落盤驗證入口)。

3files at-cap；cleanup preCreateProcess auto-review拒絕、process/deletion0，STRICT NO-RETRY；禁換tool/path/owner、逐檔/rename/containing-tree、copy/export/publish/newdiskcases。ENTIRE DAY-RANGE worktree/branch＋.range-ui-01a1106d2555430B/232files/94dirs兩次拒絕同fence，排除ALLcleanup；不掃Temp/HAR/GPG/cache/log/history。Chips memory隨正常退出釋放，private disk仍在；功能與清理分報，非global disk0／all raw released。24index calendar不代20／21 stock closes；trend／strategy／PIT／time／execution及完整ROADMAP未完成。Freeze／索引／commit／merge尚待原task，不回寫final hash。

## 34. M1-SAVED-PRICE-CHIPS-FOCUS-1006-1：保存行情與法人條件關注准入及日曆缺口

**本批只接受 guarded unavailable 操作；正向法人篩選、真零候選、joint detail及八RAW返回未驗收。** 新入口／consumer／API／guards已實作，但首次金融capture的10月日曆含10/7，超出原immutable10/6用途；20daily GET0、沒有本輪12net。操作界線見[個股頁 §39](STOCK_RESEARCH_PAGE.md#39-m1-saved-price-chips-focus-1006-1八條件入口與不可用驗收邊界)，原§29～33的具名歷史驗收不擴張成本輪成功。

### 34.1 新用途及精確篩選契約

ROOT在implementation及兩項有限來源使用前准入 `m1-saved-price-chips-focus-tpex-2026-10-06.1`，canonical UTF-8 **14399B**、SHA `1b48fc6bb23b021f3d289c797b8d077af4576f492cbc08953d0515ef0da89416`；新schema `price-saved-chips-focus/m1-v1`。New pin與§33原capture／storage／saved-focus／chips／joint五組version/digest各自重驗；不以received policy自建expected pin，不改原schemas、W8、calendar、default、七股private pins或兩股chips scope。

新 `GET /api/focus/price-saved-chips`只接受一次且全部required的 `as_of/min_lots/day_move/min_turnover/min_range_pct/investor/horizon/min_net_lots`，body須0；missing／duplicate／unknown／invalid為422，unsupported cutoff先unavailable／private0。僅explicit2026-10-06；investor為foreign／trust／dealer、horizon原字串5或20。四price條件沿§32.2精確AND，再AND selected investor的true horizon net shares ≥ signed張門檻換算的shares，含等號，依code排序，不是ranking。

`min_net_lots`最多21字、grammar `-?(0|[1-9][0-9]*)([.][0-9]{1,3})?`，另拒negative zero、超出signed int64 shares、加號／空白／逗號／exponent／前導零。最多三位小數，以精確整數scaled1000，`-0.001`為-1股；不用浮點或顯示約值filter。Eight RAW原字串及尾零應保留；這是實作契約，負門檻actual操作尚未驗收。

Prices先完整驗原七股，joint候選只3105／6488；3293／5274／5347／6510／8069為scope排除，不記成法人零。Only ALL7 price＋BOTH chips來源／窗口完整並同cutoff／provenance才可宣告available count0；其他情況count=null／items=[]。同generation明示NEW private snapshot及held chips核對成功才能解除BOTH mask；失敗capture不可retry／restart／newproducer或hydrate舊memory。

### 34.2 Existing private用途與本輪讀取

唯一root/bundle及三檔full bytes/SHA/mtimeNS、兩層UTC沿[§33.2](#332-existing-private有限只讀)原值；本批另准有限只讀，不擴保存／copy/export/publish用途。Raw/capture/storage caps3145728/8192/16384B，bundle3170304B／one bundle／3files／原3dirs；shared≤64snapshots/192files，producer61、ROOT reserve3。Actual4producer＋3ROOT＝7/21，首次未完成assertion仍計quota；完整七股126原欄／42金融、12194data rows／18欄header及canonical relationships已核，post-stop三檔bytes/SHA/mtimeNS不變。原始失敗與修正收據留ROOT task，沒有private來源完整性失敗。

Entry/apply/switch/back/capture completion無明示read則private0；new productdisk0／DBmut0，19DB schema/values/cell typeof與guards0保持。Snapshot10s／batch180s為cooperative檢查，32/64/96MiB retained graph bounds為估算，非OS硬deadline／RSSpeak。

### 34.3 首次capture的實際日曆阻擋

ONE fresh producer／ONE trusted FIRST capture沿§31有界兩份11391 index＋20daily用途；實際只取index2＝1502B，daily0、price financialGET0／外部metadataGET0。Sep1170B有效20rows／120原欄；Oct332B有5rows／30原欄，含10/7 extra row而超出原immutable10/6 schema/policy。ROOT獨立兩body＋ORIGINAL canonical receipts／Gregorian六欄／provenance／時間全核；完整SHA/UTC及累積來源用量留原task，不把index讀取換算成20daily或本輪12net。

新focus consumer capture_attempted=true／can_capture=false；legacy institutional can_capture=true僅cached guard（actioncached/request_count2），不增加fetch。後續private read仍unavailable，不取daily／retry／restart／另開producer／oldhydrate。兩held原body與receipts的ROOT memory核對不增加financialGET。日後calendar替代方案須另有fresh parser/schema/policy／用途准入，不自動授權略過extra date。

### 34.4 接受與未完成

Coreoperation0／dependency0／reliability0／**stall1**（承前0）；新增seam、memory checks及actual拒用不算解除正向joint操作依賴。Matching／verifiedzero／jointdetail／八RAWback、負門檻actual與actual missing-private-file UI均未驗收；後者NOT RUN。必要checks、原失敗與owned退出見[開發入口](development-baseline/README.md#m1-saved-price-chips-focus-1006-1-八條件入口的零落盤驗證入口)。

私人1791644B／3files／原3dirs ATCAP，原cleanup preCreateProcess auto-review拒絕／process0／deletion0，STRICT NO-RETRY；禁alternative tool/path/owner、逐檔／rename／containingtree、copy/export/publish/delete/newdiskcases。ENTIRE historic DAY-RANGE worktree／branch＋.range-ui-01a1106d2555430B／232files／94dirs兩次拒絕，retain／excludeALLcleanup；不掃Temp/HAR/GPG/cache/log/history、TURNOVER或較舊資源。Chips held memory隨正常退出釋放，private disk保留；功能／清理分報。完整ROADMAP、20／21stock closes、trend／strategy／PIT／time／execution未完成。


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

唯一private root／bundle、三檔full bytes／SHA／mtimeNS、兩層UTC及ATCAP／NO-RETRY沿§33.2與[協作紀錄](TASK_COORDINATION.md)，本批只准精確有限READ-only，不新增保存／copy／export／publish／delete。Producer新上限54snapshots、ROOT reserve3、新總57；承前7後shared≤64bundles／192logicalfiles，不能用oldconsumer96作本批上限。Actual26producer＋2ROOT＋inherited7＝35bundles／105logicalfiles，ROOT reserve1未用；ROOT兩次實讀含post-stop原三檔bytes／SHA／mtimeNS不變，children actualprivate0。

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

Private exactroot／三檔full SHA／mtimeNS／原receipts／UTC沿§33.2及[協作紀錄](TASK_COORDINATION.md)，只READ-only，禁止新增保存／copy／export／publish／delete。承前35bundles/105logicalfiles，新producer26＋ROOTreserve3＝29/87另准；實際producer26＋ROOT2，使FINAL63/189≤shared64/192，producer26 SPENT／ROOTreserve1未用；oldconsumer96不改，不reset quota，剩1bundle/3files非未來grant。

ROOT1 UTC13:11:03.008032Z～13:11:03.052032Z及finalROOT2 UTC14:03:55.687262Z～14:03:55.721262Z（均2026-10-07）獨立核完整三檔bytes／SHA／decimal mtime、全12194×18與七股原18欄；body1788599B＋capture1461B＋storage1584B＝1791644B與original JSON／mtime均不變。Children actualprivate0，沒有第三次ROOT讀取。

### 37.4 有限接受與下一缺口

ROOT接受source20及七股positive／verifiedzero／samecutoff七detail／八RAWback、新profile負值cards與actual502清兩來源；coreoperation+1／standalone coredependency0／reliability+1（scope7全7×2×3 aggregate int64 overflow guard）／stall0→0。Actual missing-private-file與post-stop recovery NOT RUN，synthetic不代actual；舊§36 negative card修正後native NOT RUN仍保持。Checks與退出見[開發入口](development-baseline/README.md#m1-saved-price-chips-focus-stock-scope-7-1006-1-七股八條件的零落盤驗證入口)；DOC review／freeze／qualified index／commit／另准master merge待。

Private3files1791644B＋original3dirs ATCAP／preCreateProcess approval REJECTED／process0/delete0 STRICT NO-RETRY，禁alternate tool/path/owner/tree bypass與新disk/copy/export/publish/delete。DAY/TURNOVER/MAIN五cache＋holiday/older資源排除及禁sweep完整條件見[協作紀錄](TASK_COORDINATION.md)；清理與功能分報。

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

Current metadataGET0／ordinarypriceGET0／privateactualIO0／upstreamPOST0；Source22 SPENT。Inherited114＋22＝136 chips GET，known17444540B另有first old Sep body unknown，不稱所有歷史bytes已知。控制項、返回及held READ不能重取得來源；FIRST不能重複。Private FINAL63bundles／189logicalfiles、剩1bundle／3files不是新grant／reset／retry／thirdROOTread；完整ATCAP、STRICT NO-RETRY及DAY／MAIN／其他資源fences見[協作紀錄](TASK_COORDINATION.md)，本批不碰private。

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
