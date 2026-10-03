# Source registry、用途 gate 與官方來源契約

更新：2026-10-03。原 snapshot 四來源的 registry、standalone capture、兩個既有磁碟 capture consumers 與第 6 節有限資料品質修正已 review，來源查證基準日仍是 2026-09-12；第 8 節 TPEx 日法人 exact endpoint 的用途准入、capture／selected 摘要與具名驗收已有限 review。第 9 節 M1-P3a 的 TWT48U 記憶體 selected 事件摘要已有限 review；第 10 節記錄 M1 後續依賴唯讀審查的來源候選與等待邊界，不新增准入。新增准入或 consumer 不修改原 snapshot／pins，也不表示已重新查證其餘三個原來源的官方現況。

本文件是免費公開官方來源的 identity、授權、用途 decision、runtime capture 與已接 consumer 的權威。第 3 節是原 snapshot 四來源，第 8 節是另需 explicit 單來源 manifest 的 TPEx 日法人准入；不能將新增來源當成 bundled default 或沿用舊 registry version。一次 HTTP 200、來源名稱或資料日期都不能補成完整 coverage、發布時間、first availability、revision lineage 或 historical PIT。

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

選中 symbol／OHLC／volume 缺失或無效仍可使 run partial；成交額 unavailable 可附 warning。upsert-only 不刪舊 bar。此來源沒有 TAIEX，不能單獨證交易 session；同日 MI_INDEX/TAIEX 須獨立成立。Matching date之外的 feed仍走原 adapter/fetcher，故不是完整 offline gate。純列 helper 有記憶體驗證；另已有限驗收單一離線落盤 fixture 的缺額／明確零經 selected capture→SQLite→API 路徑。其他 invalid／拒收的磁碟整合、真實官方來源與逐欄 coverage 仍待驗；範圍見 [P2+ 資料契約](DATA_SOURCES.md#r1-a2-p2-成交金額可得狀態有限接受)。

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

其他形狀均沿用 row-local behavior：malformed、倒置、same-day/intraday、同列雙日期、multiple cycles或 identity ambiguity不新增拒絕/reason；`interval_end` 仍可能 null並造成 legacy無界延長。Upsert可更新同 key但不刪舊錯 event，不重算既存 evaluation；完整 history capture、PIT與 repair未完成。

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

- 原四來源已有 `STOCK_DAY_ALL` 與 `holidaySchedule` 兩個有限磁碟 ZIP capture consumers；第 9 節另為 TWT48U selected 事件新增已有限 review 的記憶體 consumer，不支持既有 ZIP 讀入。TWT48U 的產品／持久化接線、`tpex_spendi_history` capture 接線與完整 legacy collector gate 仍缺。
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

本批程式 review、上述正負向操作與純記憶體靶向回歸已接受；完整 backend 回歸未跑，前端未變更而沿用仍對應來源的 M1-P1 結果。首跑含一個測試 assertion 失敗與後續修正、唯讀 fixture 核對及測試／清理的分開收據留本輪 task，不將首跑改稱全通過。Freeze／索引／commit 最終 receipt 也留 task；此 review 不增加下列多日、交易 session 或產品接線完成度。

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

三筆均為本次觀測到的**未來生效預告**，不證事件當時可得或價格影響。首次 live CLI 選到原件缺列，回 `selected_symbol_missing:6834`、exit 2，未改報通過；web 工具較舊內容不能代替實際 network 原件。測試、三次獨立 GET 的命令／版本／exit／數值／hash 及審核收據留本輪 task；現完整案例與完整 backend 未重跑，既有磁碟分支的 mock shape 驗證不當成磁碟出版驗收。本批沒有前端變更，不新增 API／UI 驗收。

此 memory consumer 不支持既有 ZIP 讀入，P3a 本身不接 API／UI／DB，`durable_capture=false`、`historical_pit=unsupported`；完整歷史、事件群組／修訂與產品研究條件仍未完成。後續 M1-P3b 的 selected 總覽接線已有限 review，精確支持範圍見[個股頁 §11](STOCK_RESEARCH_PAGE.md#11-m1-p3bselected-官方事件總覽接線)，不由產品接線擴張本節來源與時間邊界。

本輪 live body／receipt 不落盤，task 只留命令、數值／分類、hash 與驗收收據；**不能離線重播這次 live 原件**。下輪可重新取得來源，但內容／版本可能不同；Git 的最小 fixture 可重建邊界測試，不能代替本次 live 證據。不為不可重建證據新增附件或放寬既有落盤限制。工作與後續接線見 [M1 映射](ROADMAP_EXECUTION.md#21-近期里程碑接線映射)。

## 10. M1 後續依賴審查：來源候選與等待邊界

統籌已接受 **2026-10-03** 的 M1 後續依賴唯讀審查，未改程式、manifest／pins 或用途 decision，不增加能力完成度。現行 TPEx exact 日法人 resource 未列參數，`historical_coverage` 仍 unknown；第 8 節 consumer 要求全 body 日期等於單一 `expected_date`，server 為單 ZIP／日期配置。既有核定原件只支持 **2026-10-02、910 列**的單日驗收，沒有多日原件或完整窗口證據。

[政府資料集 11391](https://data.gov.tw/dataset/11391) 的官方名稱為「櫃買指數歷史資料」，描述為提供當日收盤後的上櫃大盤指數資訊，標示免費、每日更新與 OGL 1.0；名稱與 metadata 未證明提供完整多日原件或交易日基準。[日法人資料集 11856](https://data.gov.tw/dataset/11856) 仍是每日資料，第 8 節准入不外推歷史用途。本次官方 schema 與候選原件未成功取得，transport 結果留本輪 task；尚不能核對實際欄位、日期範圍或完整性，不推論永久不可用或禁止介接。

成交日實列最多證已觀測日，不能由缺列推休市或最近 5／20 交易日完整 coverage，因此本次不建立孤立的 observed-session 計算核心冒充依賴解除。候選服務恢復後可先作有界可行性核實，成功讀取不等於來源與窗口門檻通過；主缺口、恢復條件及新統籌流程見 [ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑)。本次未重搜 TWSE T86 或 R0-B2，其原未知／待驗邊界保留。
