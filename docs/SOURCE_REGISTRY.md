# Source registry、用途 gate 與官方來源契約

更新：2026-10-05。本文負責官方來源 identity、授權、用途 gate、capture 與 consumer 契約。原四來源查證基準為 2026-09-12；TPEx 單日法人另需 explicit 單來源 manifest（§8），TWT48U selected／feed 見 §9／§11。§10／§12 保留原候選缺證；§13 是另以獨立 policy 准入並驗收的 TPEx 兩股多日 CSV／有界日曆及計算。各節有限 review 不代表其餘來源已重新查證、全市場 coverage 或 PIT。

本文件是免費公開官方來源的 identity、授權、用途 decision、runtime capture 與已接 consumer 的權威。第 3 節是原 snapshot 四來源，第 8 節是另需 explicit 單來源 manifest 的 TPEx 單日法人，第 13 節是獨立版本的政府連結 CSV policy；不能將新增來源當成 bundled default 或沿用舊 registry version。一次 HTTP 200、來源名稱或資料日期都不能補成完整 coverage、發布時間、first availability、revision lineage 或 historical PIT。

現行兩股五截止W5版本／來源／日曆與唯一60 net集中[§16](#16-m1-w5五截止法人來源與完整有界日曆)；§13–15各自保留歷史觀測，不作implicit latest。

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
