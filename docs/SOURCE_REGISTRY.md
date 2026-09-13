# Source registry、用途 gate 與首批官方來源查證

更新：2026-09-13。Round09 R1-A1／G-SOURCE 的**版本化唯讀 registry foundation 與首批四來源人工查證已通過有限 review**；Round18 C018 再完成相同四來源的獨立、顯式 opt-in `source-capture/v1` runtime；Round19 C019-B 只把已保存的 `twse_stock_day_all` 單日 bundle 接到既有 TWSE security-bar consumer；Round20 C020-B 再只把已保存的單年度 `twse_holiday_schedule` 接成多日 positive request exclusion。四個具名小批都已通過各自的有限 review。Round21 C021-C／D023-C 已完成既有 `tpex_spendi_today` code-only 停牌推論的有限資料品質修正與文件收斂。本文件的 `已 review` 不代表整個 R1-A1／R1 已完成；四來源中仍只有兩個具名有限 capture consumer，也沒有完整 collector、API、排程或正式資料庫接線。

Round22 C022-B 已通過 `tpex_spendi_history` `Serial` 身分誤用的有限程式 review：只移除 `Serial` fallback，保留既有 canonical／local compatibility aliases、日期與 consumer 行為。D024-B 本次補齊契約與證據文字；整體 R1-A1、history capture consumer、PIT 與正式資料修復仍未完成。

Round23 C023-B 已通過 `tpex_spendi_history` 唯一、嚴格跨日 split-row resume linkage 的有限 final review，D025-B 本次收斂契約與證據。這只補足符合窄條件的 suspension interval end；不回頭擴大 Round22，也不代表 history capture、完整停復牌 coverage、PIT 或舊資料修復完成。

Round24 C024-B 已通過統籌有限 final review：只修 `TpexAdapter.fetch_actions` 的兩個欄位語意，把官方「每仟股無償配股」除以 1,000 後存成每股 ratio，並以「除權息前收盤價」作既有現金股利公式的 reference price；不再把貨幣權值當 ratio 或把開始交易基準價當前收。這不是 paid subscription、TWSE、capture／registry、PIT、舊資料自動 repair 或完整公司行動能力完成。

Round25 C025-B 再通過同一 TPEx action consumer 的有限 cash precision final review：`cash_dividend` 改按 exact `CashDivdend`、`CashDividend`，再按 local compatibility `現金股利`、`息值` 取 first-nonblank，沿用一次既有 `parse_number`。這項 R25 契約取代 Round24 當時刻意保留的 cash precedence，但不回寫或擴大 Round24 原驗收；也不代表官方 quote／tick 進位、paid subscription、TWSE、來源准入、PIT 或舊資料修復已完成。

Round26 C026-B 已通過 TWSE 公司行動來源分類的有限 final review：只在 `GET /instruments/{symbol}` 的既有 `corporate_actions[]` 增加 read-only `source_action_classification`，以保存的 TWSE exact `Code`／`Date`／`Exdividend` 和本地 instrument/action identity 作 fail-closed 分類；既有 `type`、DB identity、worker、factor、raw、schema 與前端均不改。這不是 capture consumer、官方事件 ID／authenticity、PIT、舊資料 repair 或完整公司行動完成。

## 1. 範圍與既有邊界

`backend/worker/sources.py` 已有 `EndpointSpec(name, url, layer, notes)` 與 `OFFICIAL_ENDPOINT_CATALOG`；Round09／18 都不是把「沒有 catalog」當問題，也不更換既有官方 collector。現有 catalog 只提供有限識別 metadata，尚不能回答同一來源可否用於本地擷取、raw 保存、摘要或歷史 point-in-time replay；用途事實仍以 registry 與具名 runtime gate 分開判定。

Round09 的來源查證與 Round18 runtime allowlist 都只含四個已存在的官方 GET endpoint：

1. `twse_stock_day_all`：上市個股日成交資訊。
2. `twse_holiday_schedule`：集中市場開（休）市日期。
3. `twse_twt48u_all`：上市股票除權除息預告表。
4. `tpex_spendi_history`：上櫃歷史公布暫停／恢復交易股票。

其他官方、媒體、國際、分點或付費來源均為未審；不得把這四筆的結果外推成 R1 全來源准入。Round09 沒有批量收集、繞過登入／CAPTCHA／429、建立排程、接外部帳戶或寫入正式／`.local` DB；Round18 只新增一次一來源的 standalone capture，仍沒有上述擴張或任何 DB 寫入。

## 2. Registry 契約

CLI 與 policy decision 必須顯式指定 manifest；不能 implicit latest，也不能只信 manifest 自報的版本或 digest。library 的 `load_manifest()` 可讀 bundled 固定 snapshot，僅是便利入口，不是挑選 latest，也不能因此自稱已外部 pin。只有外部同時 pin `registry_version` 與 canonical digest 才可稱 `pinned`；只有 version 時是 `version_only_unverified`，兩者皆無時是 `unverified`。manifest 層保存 `schema_version`、`registry_version`、`policy_version`；每個 source row 保存相同 `schema_version`／`registry_version` 與自己的 `source_version`，才能驗證結構、政策及來源版本並發現「版本字串不變、內容漂移」。來源項目至少保存：

| 類別 | 必填內容 |
| --- | --- |
| identity | 穩定 `source_id`、dataset id／名稱、來源類型、營運者／資料提供機關、endpoint、HTTP method、endpoint／schema 版本。 |
| evidence | 官方 Swagger、資料集頁、授權條款與網站條款 URL；各證據的 `checked_at`。 |
| access | 公開／需驗證、是否免費、授權版本、顯名與完整性條件、已知限制；不能由一次 HTTP 200 推定權利。 |
| operation | 更新頻率、發布時點／延遲、rate limit、重試／429 邊界。查不到時保存 `unknown + reason`。 |
| time/history | 資料描述日期、first available、歷史範圍、revision／withdrawal、supersedes 與 point-in-time 可重建性。 |
| retention | 可否 `raw_store`、可否 `summarize`、最小保存 metadata／attribution；raw 與摘要權利分開。 |
| lifecycle | `enabled`、當前 Swagger catalog 狀態、endpoint-specific deprecation／停用／通知方式、一般停止提供條款、registry policy version；「目前可見」與「未來通知政策未知」分開。 |
| purpose policy | `local_fetch`、`raw_store`、`summarize`、`historical_pit` 各自的事實狀態、理由、證據與限制。 |

### 2.1 狀態與決策不得混用

- 底層 evidence status 用 `known`、`unknown`、`explicitly_prohibited`；「官方文件沒寫」是 `unknown`，不是禁止。
- 用途 policy status 用 `admitted`、`denied`、`unknown`；某用途的正面證據不得讓其他用途自動通過。
- 對外 decision 回 `allow`、`restricted`、`unsupported`，另帶 machine-readable `reasons` 與 `conditions`。Round09 policy engine 的 `allow` 只表示**該來源＋該用途＋該 profile 的 policy eligibility**，不單獨證明 runtime 已履行 `conditions`。Round18 只有 `worker.source_runtime capture` 會在自己的 standalone path 執行 `local_fetch`／`raw_store` 的固定 conditions；其他呼叫端與 legacy collector 不會因此自動受 gate 或取得已履行聲明。
- 該用途的必要 evidence 未知、來源 `enabled` 未知／false、endpoint／method mismatch 或版本 pin／digest 衝突都 fail closed；但 deprecation notice、數字 rate limit 等**非該用途必要 evidence**的 unknown 只保留為 limitation／condition／reason，不反向阻擋已有正面證據的其他用途。`historical_pit` 未通過也不能封鎖 `local_fetch`、`raw_store` 或 `summarize`。
- `restricted` 表示有明確可做的較窄界線或必要 evidence 尚未知，不等於 `denied`；`unsupported` 也必須保留原始事實是未知還是明文禁止。
- `source-policy/v1` validator 固定每個用途的最小 `required_evidence` 與 `conditions` 集合；manifest 不能靠刪空或少列清單繞過。`local_fetch` 要求 `free_public` known true、`auth` known false 及非空的 documented terms；`raw_store`／`summarize` 分別要求自己的 retention evidence known true；所有用途另要求 `enabled` known true。各用途的 known/null、錯型別或相反布林都 fail closed，不把 `local_fetch` 的 auth 條件誤套到保存或摘要用途。

### 2.2 Runtime 邊界

Round09 registry 仍是獨立、唯讀的 manifest inspect／validate／decision foundation。`PolicyDecision.conditions` 讓呼叫端看見 `bounded_requests`、`respect_endpoint_limits`、`attribute_source`、`preserve_source_integrity`、`retain_traceability` 等義務，但 registry 模組本身不執行網路請求、raw 寫入或摘要，也不驗任意呼叫端是否履行。Round18 在另一個獨立模組加入一條已 review 的有限 executor；既有 collect 不會因檔案存在便自動套 gate。文件只能對這條具名 capture path 宣稱已執行四個固定 condition，不能宣稱 runtime 全面 enforce。synthetic fixture 仍只證介面與失敗行為；實際來源觀測另看 §7.1 的單次 live evidence。

### 2.3 Round18 `source capture` opt-in（有限 standalone runtime 已 review）

Round18 新增獨立命令 `python -m worker.source_runtime capture`，只為首批四個已審官方 GET endpoint 提供一次性的有界 raw capture。實際 CLI 固定要求 `--manifest`、`--profile`、`--source`、`--expected-registry-version`、`--expected-digest` 與 `--output-dir`；library `capture(...)` 對應接受相同 selectors，只有 local test 可注入 transport。

命令每次都必須顯式收到 manifest path、profile、`source_id`、預期 `registry_version`、預期 canonical digest 與 output directory；不得讀 implicit latest、只信 manifest 自報 digest、由 URL 反推 source，或因 registry 檔案存在而自動改變 legacy collect／daily／backfill。runtime allowlist 固定為本文件 §4 的四組 `source_id + exact URL + GET`；manifest 之後新增的 row 不會自動進入可執行集合。

在任何網路或檔案 action 前，executor 必須完成 pinned manifest validation、profile／source version／exact endpoint／method 核對，並分別取得 `local_fetch` 與 `raw_store` 的 `allow` decision。它也必須先確認兩個 purpose 回傳的每個 condition 都有已知、可執行的 handler；未知 condition、未支援 condition、manifest 新增但本地 executor 無法可靠履行的 known numeric limit，全部 fail closed，不能先抓取再補 receipt。

本批 condition 的最小可觀測語意如下：

| condition | 本批執行／證據 |
| --- | --- |
| `bounded_requests` | 每次命令對選定 exact endpoint 只送出 **1** 次 GET；沒有 retry、redirect follow、CDN warm-up 或替代 URL。上限是 5 MiB；HTTP client 的 15 秒是 per-operation timeout，另有只在 streamed chunks 之間檢查的 30 秒 cooperative deadline，明確不是 hard total deadline。任何超限／逾時都不把 partial body 發布成成功 capture。 |
| `respect_endpoint_limits` | 這只是本地保守執行政策：`trust_env=false`、單次 GET、零 retry／redirect／warm-up，任一非 2xx 即停止；429／503 的 `Retry-After` 會原值出現在 failure receipt。manifest 的 `rate_limit` 事實物件原樣保留；目前四筆為 `unknown`，因此 `rate_limit_verified=false`。若日後變成 known／explicitly prohibited 或 condition 集合不再是本 executor 實作的 exact set，會在零 request 時 fail closed。不得宣稱已驗官方配額、跨執行或多 process 的全局節流。 |
| `attribute_source` | `receipt.json.attribution` 保存 owner、dataset id、source id／URL、terms、source evidence 與兩個 purpose evidence；manifest version／digest pin、source version、exact endpoint／method 則保存於 receipt 頂層。這些必要欄位缺漏時不得成功。 |
| `preserve_source_integrity` | `body.bin` 保存 HTTP transfer framing 後、content decoding 前的 identity entity bytes；送出 `Accept-Encoding: identity`，非 identity `Content-Encoding` 直接拒絕。成功前會驗 strict JSON，但不以 parse／重排／重新序列化改寫 body；receipt 的 SHA-256 與 byte count 對應同一 bytes。 |

成功輸出只允許寫到**專案外**、當次新建或原為空的明確 directory；不存在的 output directory 必須已有 parent。不得寫正式／`.local` DB，也不得覆寫既有 capture。對外只發布 ZIP_STORED 的單一 `capture.zip`，成員順序為 `body.bin`、`receipt.json`；receipt 使用 `source-capture/v1`，記錄 aware UTC `request_started_at`／`captured_at`、body SHA-256／bytes、HTTP status、manifest／source pins、兩個 purpose decisions、condition receipts、rate-limit evidence 與 attribution。完整 body 與 receipt 先在 staging 組成，再以 exclusive hard link 發布；target／lock／其他檔案衝突或 filesystem 不支援 hard link 都 fail closed，不覆寫競爭者，也不留下本程式擁有的 half bundle。失敗 receipt 只由 library return／CLI stdout 輸出，CLI exit 2，不另寫 failed artifact。

這個 opt-in 命令只證明具名 standalone capture path 可執行首批四來源的 `local_fetch + raw_store` conditions。它沒有解析成 session／action／suspension truth，也不接既有 `sources.py`／`pipeline.py` collector；`summarize`、`historical_pit`、C007 strict time evidence、worker／產品 persistence linkage、排程與全來源准入仍分別未完成。HTTP 200 或可解析 JSON 仍只代表該次 transport／shape 觀測，不是來源 truth、完整 coverage、發布時間、first availability、revision lineage 或 PIT 證據。

### 2.4 Round19 `STOCK_DAY_ALL` selected-security bars 接線（有限內容／既有 consumer 已 review）

Round19 只處理 `twse_stock_day_all` **單一 market date、caller 明確選取標的的 security bars**。具名 library flow 是先以 `load_stock_day_capture(capture_zip, manifest=..., profile=..., expected_registry_version=..., expected_digest=..., expected_market_date=..., output_dir=...)` 完整驗證並 materialize，成功取得的 capture object 再傳給 `TwseAdapter(stock_day_capture=capture)`，最後由 `OfficialMarketDataAdapter` 送入既有 `collect(..., force=True)`。這條新能力沒有 CLI；若既有 request key 已有成功 run，library caller 必須用 `force=True` 才會實際消費 capture。未提供 `stock_day_capture` 時，既有網路／legacy 行為不變；這也不是全離線 gate，matching date 以外的 TWSE feed、同日 `MI_INDEX`／TAIEX 與 TPEx 仍走原 adapter／caller 注入的 fetcher。

loader 要求 capture ZIP 只有 ZIP_STORED 的 exact `body.bin`／`receipt.json`，並重驗 bytes／SHA-256、receipt schema／成功狀態、`twse_stock_day_all`、exact endpoint／GET、external registry pins、source version、`local_fetch + raw_store` decisions／conditions，以及 aware UTC `captured_at`。它完整驗證後才在 caller 指定、專案外 output 以 lock 與 exclusive `xb` materialize plain `body.bin`／`receipt.json`，且只在全部步驟成功時回傳 capture object；既有輸出、競爭寫入，或 materialized body／receipt 與 capture object 的受驗時間、hash、body 欄位不一致都會拒絕。這個 plain-file publication 不提供雙檔原子性，也不是永久 immutable storage；每次 `select(...)` 都會重驗 body、receipt 與上述 metadata，但 local unsigned metadata 不是 authenticity proof，也不防惡意 Python caller。

內容驗證先作用於全 body：payload 必須是非空 JSON object array，每列 `Code` 非空且全 body 唯一，所有 `Date` 可解析、同日且等於 `expected_market_date`；空 code、duplicate code、錯日、混日或 missing date 都在選列前拒絕整個 snapshot。field-level validation 只作用於 caller 要求的 symbols：OHLC 必須完整、有限且為正值；`TradeVolume` 必須是非負、未超過 signed 64-bit 的精確整數，`TradeValue` 非負，並符合 `high >= max(open, close)`、`low <= min(open, close)`、`high >= low`。數字先以 `Decimal` 解析，故 `9007199254740993.0` 可精確接受為整數 `9007199254740993`，不先經 binary float。selected row 缺失、缺欄、空值、非法／非有限／負值或價格關係錯誤都成為具 symbol 的 stable unavailable reason，不補 0；非 selected rows 不產生分類、OHLCV 完整或全市場 coverage 聲明。

capture 對 matching date 的 selected TWSE security rows 具權威性：同日 `MI_INDEX` security rows 不得補回 capture 的 missing／invalid symbol；其他歷史日期仍使用 legacy MI_INDEX security rows。合法列沿用既有 `BarRecord`／`FetchedPayload`，保存原 body hash、aware UTC `captured_at` 與 materialized `body.bin`／`receipt.json` refs；capture UTC 寫入新 `RawPayload.collected_at`，`MarketBar.collected_at` 仍是 ingestion-now。raw reuse 的完整 key 是 `ingestion_run_id + source + endpoint + sha256`，只有相同 run／endpoint／body 才重用舊 raw row、path 與 timestamp。`adj_close` 仍由既有 persistence 以 `record.adj_close or record.close` fallback 保存，這不是 adjustment truth。

missing／invalid selected symbol 會留下 warning；只要另有足夠資料且無 fatal condition，既有 run 可為 `partial`，但 upsert-only 流程不刪除同 symbol/day 的舊 `MarketBar`，所以不能把本次拒絕解讀成舊 row 已從所有 consumer 消失。`STOCK_DAY_ALL` 不含 TAIEX，也不能單獨建立交易 session；session 必須由獨立的當日 MI_INDEX／TAIEX 證據成立。capture `Date` 只證 market date，`captured_at` 只證本系統收錄時間；published／first-available／revision time、C007 store linkage、availability truth、B5b／PIT、summary gate 與正式分類均未完成。

### 2.5 Round20 `holidaySchedule` positive exclusion 接線（有限內容／既有 consumer 已 review）

Round20 只處理 `twse_holiday_schedule` 的**單一具名年度、明確休市日 positive exclusion**。library flow 先以 `load_holiday_capture(capture_zip, manifest=..., profile=..., expected_registry_version=..., expected_digest=..., expected_schedule_year=..., output_dir=...)` 驗證並在專案外 materialize，再把 `HolidayCapture` 傳給 `TwseAdapter(holiday_capture=...)`。它只在 `fetch_bars(start, end)` 的多日分支替代既有 holiday GET，讓已明確核定的 closed weekday 不送 `MI_INDEX`；單日範圍不使用 holiday capture。未提供 capture 時 legacy network 分支不變；顯式提供但驗證失敗時不 silent fallback。既有 request key 已成功時，caller 仍須 `collect(..., force=True)` 才會實際消費 capture。

loader 重驗 ZIP_STORED exact `body.bin`／`receipt.json`、bytes／SHA-256、receipt schema／成功狀態、`twse_holiday_schedule`、exact endpoint／GET、external registry pins、source version、`local_fetch + raw_store` decisions／conditions 及 aware UTC `captured_at`。全 body 必須是非空 object array；每列必要 `Name`／`Date`／`Weekday`／`Description` 都是 string，額外欄可保留。日期接受契約明列的 ROC／Gregorian compact、slash、hyphen 格式，必須可無歧義解析、全 body 唯一且全屬 `expected_schedule_year`；中文 weekday 必須與實際日期一致。每次 `select(start, end)` 都重驗 materialized bytes、receipt、hash、year 與 capture time；range 可跨年，但只選該 capture 年度內的 explicit closed dates，其他年度照常查詢，不把無列資料當休市或開市證據。

closed grammar 刻意窄化：有限 holiday-name allowlist 加 exact `依規定放假1日。`、日期／weekday／日數可重算一致的多日放假／補假完整句，以及 exact `市場無交易，僅辦理結算交割作業` 加空 Description。受控 `<br>`／空白正規化以外不做模糊 substring 推論。開始交易、春節前最後交易及其他 unknown wording 都不排除日期，也不升格成 open-session truth。calendar 只控制本次 request，不加入 `OfficialBatch.no_data_dates`，不自行產生／刪除 bar、TAIEX 或 session，不建立完整 calendar coverage；同一 collect 的其他來源仍可正常寫入其他日 `MarketBar`。既有 collect 是 upsert-only；DB 原已存在的 closed-date bar／session 不會因此刪除或修正，所以「本次不新增 session」不是 existing calendar consistency repair。

衝突只對本次流程實際可見且有效的 OHLC fail closed：daily feed（包含未選 symbols 或 `STOCK_DAY_ALL` capture）與 `TwseAdapter.fetch` 內另取的 current index 若落在 explicit closed date，不能讓 calendar 或價格任一方靜默勝出。被 calendar 略過而未抓取的 MI_INDEX 沒有可見內容，不宣稱已檢查其可能矛盾或全市場 truth。holiday raw 仍須以原 SHA、aware UTC 及 materialized refs 進既有 payload／raw audit；`Date` 只證 schedule content，`captured_at` 只證本系統收錄時間，不補 published／first-available／revision、歷年 archive、PIT、C007／B5b、ATR strict calendar／halt provenance 或 R1-A3。

### 2.6 Round21 `tpex_spendi_today` code-only 停牌推論修正（有限資料品質修正已 review）

本批不新增來源或 capture loader，只修正既有 `TpexAdapter.fetch(...)` 對 `tpex_spendi_today` 的過度推論。櫃買中心 OpenAPI 將該 endpoint 描述為「上櫃當日公布暫停／恢復交易股票」，schema 同時包含 `Date`、`SecuritiesCompanyCode`、`CompanyName`、`暫停交易`、`恢復交易`；它不是「目前仍停牌股票」清單。修正前 `parse_suspended_symbols(...)` 只提取非空代號，`TpexAdapter.fetch(...)` 再依該集合把 `end` 日同代號 OHLC bar 覆成 `is_suspended=true`；因此連恢復公告或缺少狀態欄的列也可能污染 bar 旗標。既有程式另可靜態追到 effective-session／return／signal eligibility 等下游，但本批目前只把已重現的 tracking trigger／comparable 差異列入實證。

已 review 的最小修正停止以 today row 的**代號存在**單獨覆寫 bar；endpoint 仍照既有 collector 抓取並保存 raw，非空公告只在既有 warnings list 留純文字警告，不新增 machine-readable reason code／schema；空列也只代表這次回應沒有公告列，不能證明標的開市。這不是把 `tpex_spendi_today` 加成 registry 第五筆，也不改 Round18 四來源 allowlist、`tpex_spendi_history` parser、既有 `Event` persistence 或 `_suspension_gap_between(...)` tracking 規則。

時間角色必須分開：

| 欄位／時間 | 可表示 | 不可表示 |
| --- | --- | --- |
| today/history row 的 `Date` | source row 的資料日期；須另驗格式與一致性後才能使用 | 不是暫停／恢復 `event_date`，也不是 caller `end`、published time 或 first availability。 |
| `DateOfSuspendedTrading`／`DateOfResumedTrading` | 事件的生效／排程日期 | 事件日在未來不等於資訊當時不可合法得知；也不能反過來證明它在任一更早 as-of 已知。 |
| collector `end`／現存 `data_as_of=end` | caller 要求的研究截止日 | 不能冒充無查詢參數 current snapshot 的 source observation／publication time。 |
| raw `collected_at`／standalone receipt `captured_at` | 本系統實際觀測與保存該 bytes 的時間 | 不是官方發布或逐列 first-available；較晚 capture 不能證明較早決策時已可得。 |
| first availability／revision lineage | 只有官方逐筆發布、版本、撤回／更正證據可成立 | 目前仍 `unknown`；today/history 名稱、HTTP 200、事件日期或單次 snapshot 都不能補成 PIT。 |

`DateOfResumedTrading > caller end` 的候選不能一律刪除：它可能是已公告的未來恢復排程。只有當受驗的觀測／first-available 時間不晚於決策 cutoff 時，才可在 historical decision 中使用；目前 legacy event path 沒有這項 strict evidence。本批因此不改 future `resumed_date` 的保存或 tracking 消費，也不宣稱既有 tracking 已具 PIT 安全性。

驗收矩陣：

| 案例 | 最小預期 |
| --- | --- |
| today row 只有代號、恢復公告，或暫停／恢復欄位不能證明 `end` 日停牌；同日有正常 OHLC | bar 不因 code-only today row 變成 suspended；已重現的 tracking trigger／comparable 不得只因該列被阻斷。其他靜態下游不是本批獨立實證。 |
| today 回應非空 | raw／hash／取得時間沿既有 audit 保留，並在既有 warnings list 留純文字「公告未作 current-state truth」警告；不承諾 stable reason code。 |
| today 回應空 | 不新增 suspended flag，也不升格成 open-session truth。 |
| history row 有 suspension／resumption dates，包括 future resumed date | 既有 parser、details、事件篩選與 tracking 行為不在本批改寫；限制明載為非 PIT。 |
| today／history transport 失敗 | 沿用既有 unavailable warning 與 partial 邊界，不以空資料替代。 |
| 隔離 collect／DB | 需證 raw 仍保存、正常 OHLC 不被 code-only 覆寫、真實 pipeline 結果改正、integrity／FK 通過，且正式與 `.local` DB 未變。 |

同一成功 request key 的 `force=False` 可直接 zero-call reuse，不會重新抓取 today announcement，也不會修正舊 `MarketBar.is_suspended`；`force=True` 的新 fetch 可依新 bar 正規化覆寫同一日旗標，但不自動重算既存 `SignalEvaluation`，也不修其他日期。既有 partial run 不符合 success reuse 條件，`force=False` 仍會重抓。這些是本批運維邊界，不是 retroactive repair 或 replay。

本批官方 catalog 證據限於專案外 `C:/Users/YiCheng/AppData/Local/Temp/stock-r21-coordinator-review/official-catalog-evidence.json`：一次 Swagger 回應的完整檔案在 114,176 bytes 處截斷、不能整體解析，只獨立解出 today/history 的兩個 path object 與兩個 schema object；因此只能支持上述 endpoint identity／field distinction，不能宣稱完整 catalog、live market payload、current status、歷史 coverage 或 availability truth。

### 2.7 Round22 TPEx history `Serial` 身分修正（有限資料品質修正已 review）

本批只修正既有 `parse_tpex_suspension_history_rows(...)` 的證券身分選取。櫃買中心 OpenAPI 的 `tpex_spendi_history` bounded schema 將 `Serial` 描述為「編號」，將 `SecuritiesCompanyCode` 描述為「證券代號」；因此 `Serial` 不能成為 `EventRecord.symbol`，也不能在官方代號空白時搶先匹配 `allowed_symbols`。這項判定重用 Round21 保存的官方 Swagger 證據，沒有新增 live market 或 catalog request。

已 review 的最小修正只從 identity keys 移除 `Serial`。選取順序仍是 `SecuritiesCompanyCode` → `Code` → `證券代號` → `代號`；後三者是既有本地相容 aliases，不是 exact 官方 schema 已證欄位。`_text(...)` 仍取 trim 後第一個非空值，再做 exact `allowed_symbols` membership；若較前面的 canonical／alias 非空但不在 universe，不會再嘗試較後 alias。本批不新增 alias conflict 或 value-type policy：較前面的非空欄位仍勝出，raw 與已接受 event 的 `source_row` 仍可保留非身分用途的 `Serial`。

行為邊界如下：

| 輸入 | 有限修正後行為 |
| --- | --- |
| 只有 `Serial`，即使值碰巧在 `allowed_symbols` | 不產生 suspension／resumption Event；這不證明標的開市或 history coverage。 |
| canonical 空白／null、`Serial` 非空、`Code` 或中文 alias 有效 | 略過 `Serial`，依既有 alias precedence 選證券代號。 |
| canonical 非空但不在 universe，較後 alias 可用 | 沿用既有 first-nonblank＋membership：該 row 被略過，不 fallback。 |
| canonical 與 aliases 非空且互相衝突 | 沿用既有 precedence；本批不新增 conflict validation。 |
| canonical／alias 可接受 | suspension／resumption 日期、endpoint、payload hash、raw `source_row` 與既有 event filter 保持原行為。 |

修正只阻止日後由 Serial-only 或 Serial-shadowed row 新增錯誤身分 Event。既有 `collect` 為 upsert-oriented，修正後的空列、Serial-only 列或另一證券正確列都不會刪除已存在的舊錯 Event；`success + force=False` 可 zero-call reuse，`force=True` 雖會重新抓取並保留此次擷取的 raw 證據（可能去重），也不是 retroactive cleanup。舊 Event 仍可讓 `_suspension_gap_between(...)` 與新 tracking evaluation 維持 suspended，既存 `SignalEvaluation` 也不自動重算。專案外隔離 diagnostic、repair 設計與 replay 驗證可依既有免費公開資料／本地測試授權續做；只有正式 DB 寫入／清理需另有具名授權、選取條件與回滾驗收。

本批不改 `DateOfSuspendedTrading`／`DateOfResumedTrading` parsing、future schedule、intraday time、Event persistence schema、tracking v1、first availability／revision／PIT、完整停復牌 coverage 或 `tpex_spendi_history` capture 接線。

### 2.8 Round23 TPEx history split-row resume linkage（有限資料品質修正已 review）

D025-A 保存的官方 current snapshot 揭露了既有 combined-row fixture 未覆蓋的來源形狀：362 列中 181 列只有 suspension date/time、181 列只有 resumption date/time；181 個 `SecuritiesCompanyCode` 在該 exact body 各恰有一列 start-only 與一列 resume-only，沒有同列雙日期、空雙日期、malformed、倒置或同日樣本。第二次成功 direct GET 的原 bytes 為 79,602、SHA-256 `4e3747a4a27c1e45542ce476ff7ccd0384e5c420e9f2d5bbfd9257b9cc48e6a2`，與 Round09 probe 相同。D025-A 實際共做兩次成功 direct GET：第一次只在記憶體核 shape，第二次保存原 bytes；另一次 web-open 通道回 502。成功回應只保存 `Content-Type: application/json`，完整 response headers 未取得且不再補抓。這些限制與 request count 不得改寫成「一次 fetch」。

C023-B 只在既有 identity precedence、`_text(...)` coercion／first-nonblank 與 exact `allowed_symbols` gate 之後，按同一 selected symbol 的**全部輸入列**判定；invalid、空日期與重複列也計入兩列上限。只有該 symbol 恰有兩列，其中一列以既有 `parse_roc_date(...)` 得到 start、對側 resume raw text 為空，另一列得到 resume、對側 start raw text 為空，且 `start < resume`，才建立 linkage。它沒有新增 strict date parser、alias conflict／type policy、`Serial` pairing、row-order／adjacency gate 或 time parser；跨日先後只由日期決定，兩列 time 欄保持 raw-only。

Linkage 只改 suspension Event 的 flexible details：`source_row` 仍是原 start row，`resumed_date`／`interval_end` 補為 paired resume date，並新增 `resumption_source_row` 保存完整 resume row；獨立 resumption Event 的日期、details、順序與 payload provenance 保持既有行為。這不新增 migration、Event key、schema／execution version，也不改 `TpexAdapter.fetch` 的 future event-date cutoff 或 `_suspension_gap_between(...)` 的 date-grain predicate。官方原 body SHA 與 actual adapter 對 fixture／subset 重新 JSON 序列化後的 raw SHA 是兩份不同證據，不得混寫。

不符合唯一 split-pair 的形狀全部保留舊 row-local 行為：unmatched blank、malformed nonblank、倒置、same-day／intraday、同列雙日期、duplicate／multiple cycles 或 identity 歧義都不由本批新增拒絕、reason code 或 fail-closed policy；因此某些 suspension 仍可能保持 `interval_end=null`，並在既有 tracking 形成無界延長推定。**保留舊行為是本批接受契約；針對這些形狀新增 hardening 才是明確未完成提案。**即使 linkage 讓新 evaluation 不再把 resume boundary 後的缺口歸給該 suspension，也只消除這一項 unsupported extension，不證明復牌日完整開市、完整 halt coverage、session truth 或 historical PIT。

同一 Event key 的舊 `interval_end=null` 可在實際 fetch＋`force=True` upsert 時更新 details，不新增 duplicate；相同 raw content 可由既有 dedupe 指向同一 raw row，不能寫成每次新增 raw。`success + force=False` 仍可 zero-call reuse，不消費新 parser；舊錯身分 Event 不刪，既存 `SignalEvaluation` 不重算。專案外 diagnostic／repair design／replay 仍在既有免費公開資料與本地測試授權內，不需重複請示；正式或 `.local` DB cleanup／replay 寫入仍未授權。

### 2.9 Round24 TPEx 公司行動 ratio／reference mapping（有限資料品質修正已 review）

D026-A 對現行 consumer 與官方欄位做分離查證。[TPEx Swagger](https://www.tpex.org.tw/openapi/swagger.json) 的 exact daily schema 定義 `StockDividend=權值`、`StockDivdendThousandShares=每仟股無償配股`、`ClosePriceBeforeExRightsDiviend=除權息前收盤價`、`ExRightsDiviendQuote=除權息參考價`、`OpeningReferencePrice=開始交易基準價`。[TPEx 計算頁](https://www.tpex.org.tw/zh-tw/announce/market/ex/cal.html) 另定義 `權值=除權息前收盤價-息值-除權息參考價（未進位）`，所以 `StockDividend` 是價格差額而非 ratio；每仟股配股必須除以 1,000 才是既有 factor 所需的每舊股 ratio。開始交易基準價是除權息後按檔位選取的交易基準：不含現金增資時取最接近除權息參考價的檔位，含現金增資時改取最接近減除股利參考價的檔位，因此不是現金股利公式的前收分母。

C024-B 接受契約只改 `TpexAdapter.fetch_actions` 的兩個 normalization slot：`stock_dividend_ratio` 由 exact `StockDivdendThousandShares` 或 local compatibility label `每仟股無償配股` 取第一個非空、沿用 `parse_number`，parsed non-null 才除以 1,000；移除 `StockDividend`／`權值`／`無償配股率` fallback。`reference_price` 改讀 exact `ClosePriceBeforeExRightsDiviend` 或 local compatibility label `除權息前收盤價`；移除 `OpeningReferencePrice`／`開始交易基準價` fallback。中文 label 是 local compatibility，不冒稱 checked OpenAPI 另有中文 keys。cash-dividend precedence／精度、symbol／date／as-of／action type、raw details／payload SHA、ordering／count、missing reference 的既有 previous-official-bar fallback 均不改。

在本輪具名正常輸入案例（finite `P>C≥0`、`Rf≥0`，且無 paid subscription 或其他同日調整）中，既有 downstream factor `1/(1+Rf) × (P-C)/P` 與官方 `Q/P=(P-C)/(P×(1+Rf))` 等價；這不新增 parser 的負值／non-finite／invalid 全面 hardening，也不把 previous-bar fallback 升格成官方 Article 57 source truth。完整公式是 `Q=(P-C+S×Rp)/(1+Rf+Rp)`；現行 normalized model／factor 沒有現金增資配股率 `Rp` 與認購價 `S`，故 paid-subscription 仍會不完整。C024-B 不採 `ExRightsDiviendQuote/P` explicit factor、不 join `tpex_exright_prepost`、不改 TWSE、共用 factor、schema／execution version、capture／registry 或 PIT；不得寫成 paid、所有公司行動或 R1-A3 已完成。

D026-A 的 production endpoint snapshot 只有 ROC 1150914 的三筆 cash-only rows；以 2026-09-13 as-of 呼叫仍應因 future-date cutoff 得零筆，2026-09-14 的隔離 replay 只是 current body shape exercise，不是當時 availability 或 PIT 證明。該 daily body 沒有 non-zero free／paid row，非零 ratio 只用 official-schema-shaped synthetic 驗 conversion；另一個 `tpex_exright_prepost` body 雖觀察到 decimal free／paid ratios，並非現行 consumer endpoint。上述新 TPEx endpoints 也不在 Round09 四筆 registry admission；本節不新增第五筆准入或 capture consumer。

### 2.10 Round25 TPEx 公司行動 cash precision（有限資料品質修正已 review）

R25 沿用 D026-A 已保存且重新驗 hash 的官方 bytes，沒有新增網路請求。[TPEx Swagger](https://www.tpex.org.tw/openapi/swagger.json) 把 `tpex_exright_daily.CashDivdend` 定義為「現金股利」、`CashDividend` 定義為「息值」；[TPEx 計算頁](https://www.tpex.org.tw/zh-tw/announce/market/ex/cal.html) 以息值作公式 `C`，同時註明「息值＝每股現金股利」。分離的 `tpex_exright_prepost.CashDividend` 也是「現金股利」，而保存的三筆相同事件逐筆等於 daily `CashDivdend`。因此 C025-B 只把既有 normalized `cash_dividend` 的 first-nonblank 順序改為 `CashDivdend` → `CashDividend` → `現金股利` → `息值`：exact keys 先於 local compatibility labels，各 tier 都讓較精確的每股現金股利先於六位小數息值。

`_text` 與 `parse_number` 都未改：missing／null／empty／whitespace 才繼續下一個 key；高優先欄只要 nonblank 就被選定，再只 parse 一次，故 `bad`、`--`、`NaN` 等不會偷偷降級到較低優先欄。既有 substring number extraction、負值、non-finite／invalid policy 均未全面 harden。保存的 5278 從 `CashDividend=0.266182` 改取 `CashDivdend=0.26618165`；以 `P=23.90` 手算的 cash-only factor 是 Fraction `472676367/478000000`，而舊 factor 與新 factor 相差約 `1.4644351464e-8`。6204、8423 的數值保持 0.5、0.7。這是 normalized 每股 cash 精度修正，不證明 backend factor 與官方兩位 quote、未進位值或 tick selection 在所有小數位完全一致。

同一 action identity、date/type、free/reference、raw details／bytes／SHA／FK、順序與 future-as-of filter 均保留。作者的 actual `OfficialMarketDataAdapter` whole `collect` 證明：舊 cash 先寫入後，`success + force=False` 零 fetch reuse 仍保留舊值；`force=True` 才以新 parser 更新相同唯一 action ID，沿用相同 raw ID／exact bytes，兩個 consumer 才對新 signal 使用精確 factor。舊 evaluation 不因 collect／新增 signal evaluation 自動重算；顯式重新 evaluate 同一 signal 仍可能 upsert，不能宣稱 immutable 或既有資料已自動修復。統籌 29-check 則使用 direct `_upsert_action` 且 `raw FK=None`，不取代作者 whole-collect／raw-FK／reuse-force 證據。missing reference 的 fallback 只是既有 `MarketBar.close`；來源可能是 fixture synthetic，不能稱必為官方 previous close 或 Article 57 truth。

Paid subscription 保持 unsupported。公式需要可信 `Rp`、`S`、`P` 與持久化／版本策略；增加 normalized columns／migration 是一種方案，不是所有可行設計的唯一必要形式，既有 `details_json` 雖可機械承載 raw 欄，仍不是已准入的 normalization／factor policy。TPEx production daily 沒有 direct formula `Rp`；分離 prepost 的 4541 直接 `SubscriptionRatioToNewSharesIssued=0.07391303`，但 `SubscribedProRataInThousandShares/1000=0.05913042676`，不可把 pro-rata 欄猜成 `Rp`。TWSE 保存 body 另有 `Exdividend=息` 63、`權` 2、`權息` 3，而現 predicate 對「除息」命中 0；但 `action_type` 是 upsert identity，type-only force 會留下第二筆 cash action並被兩個 consumer 重複相乘，故不能單改。checked `TWT48U_ALL` 也沒有 pre-close/reference 欄。這些是後續可獨立工程，不在 C025-B。

### 2.11 Round26 TWSE `source_action_classification`（有限唯讀投影已 review）

D028-A 重新驗證 R24 保存的 TWSE `TWT48U_ALL` body：18,203 bytes、68 rows、SHA-256 `a344e312b7809ad9fa1d2f949c39c6095bf0fd8dfcedd4e7bdbb8bb6ef51b907`，當次值為 `息` 63、`權` 2、`權息` 3；同一 snapshot 的 `Code+Date` duplicate 為 0，但這不是長期唯一性保證。保存的 TWSE Swagger 為 309,960 bytes、SHA-256 `06e1cea82448361e733a0ad1ae16e52f5d5d6b71905acd078472f852c32c0eb0`；checked schema 有 12 個 string fields，沒有 stable official event ID、required、enum、revision 欄或 Date format 宣告，且 response 宣告 object、實際 body 為 array。故 R26 不重寫既有 `CorporateAction.action_type`／identity，而採相容的 API 投影。

`GET /instruments/{symbol}` 的每個既有 `corporate_actions[]` 現在多一個 `source_action_classification`：

| 欄位 | 契約 |
| --- | --- |
| `kind` | `ex_dividend`、`ex_right`、`ex_right_and_dividend` 或 `unknown`。 |
| `label` | 分別為 `除息`、`除權`、`除權息` 或 `未知`。 |
| `raw` | 固定形狀 `{"field":"Exdividend","value":...}`；只有原值為 string 才原樣保留（含前後空白），否則為 null。 |
| `reason` | 依下列固定 precedence 回傳一個 machine reason。 |

只有 `CorporateAction.source` exact `twse`、instrument exchange exact `TWSE`、非空 `Mapping` details，以及 `Code`／`Date`／`Exdividend` 三個 exact key 均為 nonblank string 才繼續。`Code.trim()` 必須等於 instrument symbol；`Date.trim()` 必須是 7 位 ASCII ROC date、可形成真實日曆日且等於 action date；`Exdividend.trim()` 只接受 exact `息`／`權`／`權息`。local aliases `股票代號`、`證券代號`、`除權息日期`、`除權息` 只做一致性檢查：null／blank string 忽略；其他 non-string 或與已解析 canonical 語意不一致即 fail closed，不能覆寫或補足缺少的 exact field。Date 兩方即使是相同 invalid text，也因 canonical date 無法解析而衝突；Exdividend 兩方即使是相同 unknown text，也因 canonical 值不在三個 enum 內而衝突。

reason precedence 固定為 `unsupported_source` → `invalid_details` → `missing_official_field` → `alias_conflict` → `identity_mismatch` → `unknown_raw_value` → `trusted_twse_exact_fields`。任何失敗都回 `kind=unknown`、`label=未知`，並仍按上述 raw 規則揭露 `Exdividend`。known 三值只是「本地已保存 details 與 instrument/action identity 一致」；不證 raw body membership、payload hash／FK、來源真實性、official event identity、first availability、revision、完整性或 PIT。

這個投影不改既有 `type`、action row、raw、排序、50 筆上限、worker parser、factor 或兩個 downstream consumer；因此也不合併、去重或 repair 既有同日多 type rows。C026-B external `saved.py` 的 actual adapter＋helper 對同一個 68-row 保存 body，在 2026-09-13 cutoff 輸出 6 rows（`息` 4、`權` 1、`權息` 1），到 2026-12-31 future replay 才輸出全 68 rows；這不是 whole `collect`，兩者也都只是 current snapshot shape exercise，不是 historical PIT。C026-B 的 whole-collect 證據另使用 synthetic 2026-09-04 單一 `息` row，驗 `force=False` zero-fetch reuse、`force=True` 相同行動／raw 語意、兩個 consumers factor `0.99875` 與舊 evaluation retained；既有 duplicate factor 風險仍未修。D028-A 則是無 production import 的 standard-library 26-case oracle，證據歸屬不得混稱。

## 3. 官方共同證據

- [TWSE Swagger](https://openapi.twse.com.tw/v1/swagger.json) 為 Swagger 2.0，`host=openapi.twse.com.tw`、`basePath=/v1`、HTTPS、info version `1.0`；說明頁明示歡迎 API 介接，並連到 TWSE 使用條款與政府資料授權條款。
- [TPEx Swagger](https://www.tpex.org.tw/openapi/swagger.json) 為 OAS 3.0，server 為 `https://www.tpex.org.tw/openapi/v1`、info version `1.0.0`；說明頁明示歡迎 API 介接。
- 四筆對應的政府資料集頁都標示「免費」及「政府資料開放授權條款－第 1 版」。[該授權](https://data.gov.tw/license)允許不限目的、時間及地域、免授權金的重製、散布、公開傳輸、編輯與改作，但要求明確顯名；未履行顯名義務視為自始未取得授權。這支持有條件的 raw 保存與摘要，不是免除 attribution、第三人權利或來源完整性義務。
- [TWSE 網站使用條款](https://www.twse.com.tw/zh/terms/use.html)禁止非經同意方式的自動化下載，並保留修改或停止服務的權利；本輪只把官方 OpenAPI 明示介接視為指定通道，不外推為任意爬蟲或無上限批量抓取。
- [TPEx 網站使用條款](https://www.tpex.org.tw/zh-tw/gtsm_disclaimer.html?l=zh-tw)要求引用／轉載清楚標示來源與維持資料完整，且說明經政府資料開放平臺授權的資料例外適用其開放授權。該頁的 web 擷取曾回 403，但搜尋索引可讀；registry 仍以資料集頁與 OGL 1.0 為具體授權證據，兩者不混成 endpoint SLA。

官方 Swagger 未列這四條 path 的 authentication、安全 scheme、數字 rate limit、精確發布時鐘、revision history 或 endpoint-specific deprecation notice。一次無驗證 200 只補充「當次公開可讀」觀測，不能把上述未知欄位改成已知。

## 4. 首批來源 identity、存取與保存

| source_id | owner／provider | exact endpoint／method | 官方資料集與版本 | 免費／授權 | raw／摘要界線 |
| --- | --- | --- | --- | --- | --- |
| `twse_stock_day_all` | API 營運者：臺灣證券交易所；資料集頁提供機關：金融監督管理委員會證券期貨局 | `GET https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL` | [dataset 11549](https://data.gov.tw/dataset/11549)；Swagger info `1.0` | 免費、OGL 1.0；公開 OpenAPI，未列 auth | raw 保存與摘要可依 OGL 1.0 有條件使用；保存 owner、dataset、endpoint、取得時間、hash、license version 並顯名。 |
| `twse_holiday_schedule` | API 營運者：臺灣證券交易所；提供機關：金融監督管理委員會證券期貨局 | `GET https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule` | [dataset 11761](https://data.gov.tw/dataset/11761)；Swagger info `1.0` | 免費、OGL 1.0；公開 OpenAPI，未列 auth | 同上；不得把當年 snapshot 改寫成完整歷史交易日曆。 |
| `twse_twt48u_all` | API 營運者：臺灣證券交易所；提供機關：金融監督管理委員會證券期貨局 | `GET https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL` | [dataset 89748](https://data.gov.tw/dataset/89748)；Swagger info `1.0` | 免費、OGL 1.0；公開 OpenAPI，未列 auth | 同上；raw 需保留取得時點，因 payload 可含未來預告，不得只靠事件日期宣稱當時可得。 |
| `tpex_spendi_history` | API 營運者：證券櫃檯買賣中心；提供機關：金融監督管理委員會證券期貨局 | `GET https://www.tpex.org.tw/openapi/v1/tpex_spendi_history` | [dataset 48665](https://data.gov.tw/dataset/48665)；Swagger info `1.0.0` | 免費、OGL 1.0；公開 OpenAPI，未列 auth | 同上；名稱含「歷史」不等於保存逐次發布版本或完整 PIT lineage。 |

## 5. 更新、歷史、修訂與停用 evidence

| source_id | 官方更新／上架 metadata | 發布／first availability | 官方歷史範圍 | 修訂／撤回 | rate limit | 停用／版本 |
| --- | --- | --- | --- | --- | --- | --- |
| `twse_stock_day_all` | 每 1 日；dataset 上架 2017-05-23，metadata 更新 2025-05-01 | 精確發布時鐘、每筆 first available：`unknown`，官方頁未列 | endpoint 無查詢參數；可取範圍與最早日期 `unknown` | 原版保存、修訂時間、supersedes：`unknown` | 數字上限與窗口：`unknown` | Swagger info `1.0`；endpoint-specific deprecation／notice：`unknown`。一般條款允許變更／停止。 |
| `twse_holiday_schedule` | 每 1 年；提供最新一版，通常每年 12 月前提供次年度；上架 2017-05-23，metadata 更新 2026-08-21 | 「通常 12 月前」不是精確 first available；逐版發布時間 `unknown` | 歷年 archive／完整邊界 `unknown` | 年度版本修訂、撤回與 supersedes `unknown` | `unknown` | 同上。 |
| `twse_twt48u_all` | 不定期；上架 2018-08-14，metadata 更新 2026-06-30 | 精確發布／每列 first available `unknown` | endpoint 無查詢參數；完整過去事件範圍 `unknown` | 預告更正／撤回 lineage `unknown` | `unknown` | 同上。 |
| `tpex_spendi_history` | 不定期；上架 2015-12-03，metadata 更新 2026-06-08 | 精確發布／每列 first available `unknown` | 頁面稱歷史，未定義起點、完整性或 archive policy，故 `unknown` | 修訂／撤回 lineage `unknown` | `unknown` | Swagger info `1.0.0`；endpoint-specific deprecation／notice `unknown`。OGL 只列一般停止提供事由。 |

資料集「上架日期」只證明 portal metadata 的上架日，不是每筆紀錄的 first availability；「詮釋資料更新時間」也不是 payload 發布或 revision 時間。

## 6. 用途 decision matrix（`free_public_local` 已 review policy eligibility）

| source_id | `local_fetch` | `raw_store` | `summarize` | `historical_pit` |
| --- | --- | --- | --- | --- |
| `twse_stock_day_all` | `allow` eligibility；conditions=`bounded_requests,respect_endpoint_limits` | `allow` eligibility；conditions=`attribute_source,preserve_source_integrity` | `allow` eligibility；conditions=`attribute_source,preserve_source_integrity,retain_traceability` | `unsupported`；缺 `first_availability,reconstructable_snapshot,revision_history` |
| `twse_holiday_schedule` | `allow` eligibility；同上 | `allow` eligibility；同上；snapshot 不冒充歷史全集 | `allow` eligibility；同上 | `unsupported`；僅最新年度說明，逐版 availability／revision 未證 |
| `twse_twt48u_all` | `allow` eligibility；同上 | `allow` eligibility；同上；必存 collected-at，未來預告不得倒推可得時間 | `allow` eligibility；同上 | `unsupported`；預告的 first availability、更正／撤回史未知 |
| `tpex_spendi_history` | `allow` eligibility；同上 | `allow` eligibility；同上 | `allow` eligibility；同上 | `unsupported`；「歷史」列表沒有逐次 snapshot／revision availability 證據 |

上述 `allow` 是「附 machine-readable conditions 的用途政策 eligibility」，不是單靠 policy decision 就能宣稱條件已執行，更不是既有 collector 已 enforce 的聲明。Round18 executor 只在 §2.3 的 standalone capture action 前核對 external pins、精確 endpoint／method、兩個用途 decision 與本批 condition exact set，再把執行結果寫入 receipt。其他 wiring 仍須各自在 action 前完成等價 gate 與獨立驗收。數字 rate limit 未知時，Round18 採單次、零重試／redirect、保留 429／503 `Retry-After` 的本地保守政策；這不是官方 numeric limit，也不是跨執行配額。

## 7. Round09 final review 證據

統籌以 bundled Python 3.12.14＋真 Alembic 1.19.2 執行 `python -m pytest backend -q --disable-warnings`，結果為 237 passed、4603 warnings、25.31 秒、exit 0。獨立 61／61 覆蓋 4×4 用途矩陣、12 組 condition codes、外部 pin／同版本 drift、malformed／欄位特定布林語意與最低 evidence／conditions 空清單繞過；作者 focused suite 為 16 passed。外部 evidence 位於 `C:/Users/YiCheng/AppData/Local/Temp/stock-r09-coordinator-review/` 的 `independent-review.json`、`backend-final.txt`、`protected-review.json`、`final-source-hashes.json`。

已 review manifest：`registry_version=r1-a1-c009-2026-09-12.1`，canonical `content_digest=sha256:eb6c290d7716300c4117bb2cdc61a66cbf8d62e344870928933b44b77461f87b`。最終檔案 SHA-256：

- `backend/worker/source_registry.py`：`FA2894ECC2C355A3EED295A9E2E8C6A7064DF3A38CD8615C6E135810E830AA08`
- `backend/worker/source_registry.json`：`104301791A38A01345D513D1913305C03613228A4FA7111C6C80A4AC4C5671C4`
- `backend/tests/test_source_registry.py`：`D4BE7E9AC20850CB2103CC2B20D113AB9769DA8AD2043E83373B3BA22AF8B658`

基線 23 個 protected targets 的 hash／size／mtime 全部一致；未寫正式或 `.local` DB。這輪沒有前端變更，也沒有重跑 frontend test／build／UI，因此不沿用舊 UI 結果冒充 Round09 證據。以上只結清版本化唯讀 registry foundation 與首批四來源人工查證；不是 immutable registry store、全來源完成、官方 PIT truth、collector gate、排程或交易授權。

### 7.1 Round18 C018 standalone source capture final review 證據

新增且 freeze 的 `backend/worker/source_runtime.py` SHA-256 為 `4E80D8D4977BBF317892F31593853F42E368240EA7E5C12FC2E47CEF74FA927D`；`backend/tests/test_source_runtime.py` 為 `7164630ABABD255B430BD76385DCB0BFE9B58462FB4F82A684CB46FF55BA38C2`。統籌以 Python 3.12.14、Alembic 1.19.2 跑完整 backend：519 passed、1 skipped、5,066 warnings，pytest 57.36 秒、process 58.75 秒、exit 0；驗證腳本納入 guard 的 `backend/alembic`、`backend/app`、`backend/tests`、`backend/worker`、`frontend/src` 程式／測試來源與正式／`.local` 兩 DB，其 before／after fingerprints 全部 unchanged。統籌另以獨立 script 通過 33／33 checks，涵蓋四個 allowlist source 的 exact GET／bundle integrity、既有 bundle 拒絕、零 request preflight、known quota fact、301／307／429／500／503、invalid／non-finite JSON、encoding／oversize、競爭 publication、no app／DB import 與 CLI。作者 targeted 為 54 passed、1 skipped／2.21 秒；作者完整 backend 為 519 passed、1 skipped、5,066 warnings／57.75 秒，該 pytest suite 另覆蓋 explicitly prohibited rate-limit fact、timeout／cooperative deadline 與其他 fail-closed 邊界。唯一 skip 是環境缺 symlink privilege；Windows junction 真實建立與拒絕路徑已通過，故不能把 skip 寫成所有 symlink 平臺都實跑。

統籌另對 `twse_stock_day_all` 執行一次真正 CLI／網路 capture：`request_started_at=2026-09-12T19:12:47.460199+00:00`、`captured_at=2026-09-12T19:12:47.540715+00:00`、`request_count=1`、HTTP 200、319,396 bytes、JSON list 1,379 rows，body SHA-256 `0b1aff71084982ae31d719b47fff2c975205c6173ccb6d083232b4f5eeb23cbe`；`capture.zip` 的 `body.bin` 與 receipt hash／bytes 相符，內外 receipt 相同，且沒有 legacy data 建立。這只證該時點、該 endpoint 的一次 live capture；另外三個 allowlist endpoint 只有 mock／獨立介面檢查，沒有 Round18 live 擷取，不能外推可用性或內容真值。

統籌證據位於 `C:/Users/YiCheng/AppData/Local/Temp/stock-r18-coordinator-review/` 的 `full-backend-review.json`、`full-backend.log`、`independent-runtime-review.json`、`live-capture-review.json`；live bundle 在 `C:/Users/YiCheng/AppData/Local/Temp/stock-r18-live-izyrjlk3/capture/capture.zip`。本輪沒有前端變更／驗收，也沒有建立排程、接 legacy collector 或寫兩個 DB。

### 7.2 Round19 C019-B `STOCK_DAY_ALL` content／consumer final review 證據

freeze 的 `backend/worker/stock_day_capture.py` SHA-256 為 `4caca05d473ae18f8695859fc915c497d3e051ab1ab864e6f35abd9022a80132`；`backend/worker/sources.py` 為 `fc032d0079803095b29d44570174da36b4eeba58c533214d7d3d465631e25f59`；`backend/tests/test_stock_day_capture.py` 為 `18297bae99ccb8a4609c37549105303a2d9c2176ad463f23ae602002cb2591b2`。統籌以 Python 3.12.14、Alembic 1.19.2 執行完整 backend：590 passed、1 skipped、5,198 warnings，pytest 47.27 秒、process 48.344 秒、exit 0；作者 final full 亦為 590 passed、1 skipped、5,198 warnings／47.96 秒。較早的 69-pass targeted 是新增兩個測試前的中途結果，不是 final targeted，故不作最終驗收計數。統籌 full guard 顯示 code／tests 與正式、`.local` 兩 DB 的 SHA／size／mtime_ns 前後不變；本輪文件未納入該 guard。

獨立 capture review 30／30 checks 通過：重讀 Round18 的 1,379-row bundle 得 1,367 個有效 rows、12 個 unavailable，並逐列核對 OHLC、量與成交額，且覆蓋 exact raw UTC、selected-only validation、numeric／ZIP／pin／time tamper、mutated materialized object 與既有 output rejection；未發新 live request、未改 DB 或來源。精度反例在修正前把 literal `9007199254740993.0` 誤成 `9007199254740992`；final 以 `Decimal('9007199254740993.0')` 精確接受為 `9007199254740993`，對應 final source hash 如上。

獨立既有 consumer review 7／7 checks 通過：同一保存 bundle 經真實 `TwseAdapter`、`OfficialMarketDataAdapter` 與 `collect`，輔助 TWSE 本地 fixtures、TPEx empty-batch stub，所有 HTTP 均被禁止。成功選列 `2330` 保存 capture raw hash／UTC；`1472` invalid OHLC 與 `999999` missing 產生 warnings、既有舊 bar 保留；只有完整 `ingestion_run_id + source + endpoint + sha256` 相同的重跑才重用原 raw row、path 與 timestamp；獨立 TAIEX session 原已存在且沒有新增 session。隔離結果為 `partial`、`records=2`、`taiex_records=1`、`raw_payloads=10`，integrity／FK 通過；這不是兩市場完整 live parser 證據。完整 pytest 另含兩個不屬於上述 7-check 主矩陣的 integration：雙市場本地 fixtures 驗 success、`force=False` reuse、`force=True` capture／partial／stale raw；以及 MI_INDEX unavailable＋empty index 時，即使 capture 可產 bars 仍 failed、raw 保留且不建立 bar／session。

統籌證據位於 `C:/Users/YiCheng/AppData/Local/Temp/stock-r19-coordinator-review/` 的 `full-backend-review.json`、`full-backend.log`、`independent-capture-review.json`、`volume-precision-probe-before.json`、`volume-precision-probe.json`、`independent-consumer-review.json`。本批沒有新 live 擷取、前端驗收、正式／`.local` DB 寫入、排程或自動交易；local unsigned metadata 也不是來源 authenticity proof。materialized plain files 非雙檔 atomic／永久 immutable，未使用 symbols 無 coverage 聲明，舊 bar persistence 與 `adj_close` fallback 限制均保留。這個有限 review 不結清 R1-A1、R0-B5、B5b、B7 或正式分類修復。

### 7.3 Round20 C020-B `holidaySchedule` content／consumer final review 證據

統籌以 Round18 同一 standalone runtime 對 `twse_holiday_schedule` 執行一次真正 GET：`request_started_at=2026-09-12T20:24:29.126005Z`、`captured_at=2026-09-12T20:24:29.169003Z`、`request_count=1`、HTTP 200、3,774 bytes、JSON array 27 rows，body SHA-256 `7644c1a8af784c09f54670fd7413f536b13eb76c54d658058e8873d1aee32117`。觀測到 exact required fields `Name,Date,Weekday,Description`、ROC 1150101–1151225，內容含 regular holiday、補假、多日春節、兩筆市場無交易及三筆不應排除的交易敘述；這次 body hash 與 §8 早先 probe 相同。bundle 在 `C:/Users/YiCheng/AppData/Local/Temp/stock-r20-holiday-live-8a_frrvt/capture/capture.zip`，receipt／CLI log 在 `C:/Users/YiCheng/AppData/Local/Temp/stock-r20-coordinator-review/holiday-live-capture.json` 與 `holiday-live-cli.log`。

freeze 的 `backend/worker/sources.py` SHA-256 為 `d05f2aec36c536a216d6cfb9212b8d51336192f29cdebe635a7fccab132065a6`；新增 `backend/worker/holiday_capture.py` 為 `f209f557b24777ddacba2e27d17c224d26ff7b9a56e84aa470bdd25e5bde640e`；新增 `backend/tests/test_holiday_capture.py` 為 `abb2f8abf71ae734ca021be357597193a1fbf8bc95acd8e3035ff36a8e208237`。統籌以 Python 3.12.14、Alembic 1.19.2 執行完整 backend：678 passed、1 skipped、7,201 warnings，pytest 53.89 秒、process 55.016 秒、exit 0。final guard 納入 `backend/app`、`backend/worker`、`backend/tests`、`backend/alembic`、`frontend/src` 的 code／source 與正式、`.local` 兩 DB，before／after fingerprints 全部 unchanged；本輪四份文件不在該 full-suite guard。唯一 skip 沿用 Round18 的 Windows symlink privilege 條件，作者與統籌沒有新增 skip。

統籌 final guarded independent 17／17 checks 通過：同一保存 live bundle 的 manual oracle 為 24 closed／18 weekday closed／3 non-closure，包含五個 legacy substring 漏列補假日；另驗全域年度／weekday／duplicate、negative／conflicting wording、capture object timestamp drift、2 月 26 日至 3 月 2 日 request list，以及真實 `TwseAdapter`＋`OfficialMarketDataAdapter`＋`collect`、本地 TWSE ancillary fixtures、TPEx empty stub、HTTP 全禁的隔離 consumer。結果為 `partial`、26 records、13 TAIEX、48 raw；capture raw UTC／hash／reuse、closed dates 不新增 session、integrity／FK 均通過。這個 17-check 矩陣不冒稱完整雙市場；作者測試與統籌 full backend 另實跑 combined TWSE＋TPEx fixtures、`force=False`／`force=True`、materialized bytes／receipt tamper、stale closed row 保留及 collect conflict raw persistence。作者 final holiday suite 為 88 passed、2,003 warnings／6.84 秒；作者較早的 full 676 passed、1 skipped、7,119 warnings／53.38 秒是在新增兩個測試前，不能寫成作者 final full。單一 TWSE 測試繞過 combined dedup，導致 UNIQUE 的初次測試失敗；缺 Alembic 環境的初次失敗證據也保留，修正後上述 final 路徑已重跑通過。

統籌證據位於 `C:/Users/YiCheng/AppData/Local/Temp/stock-r20-coordinator-review/` 的 `full-backend.log`、`full-backend-review.json`、`independent-holiday-review.json`、`independent-final-guard.json`；作者 delivery manifest 與 diff 位於 `C:/Users/YiCheng/AppData/Local/Temp/stock-r20-code-d1c797f46b264978be4a70de5383468d/`。本批保留以下限制：單日不 consume holiday capture；新增／未知名稱或文字只留 warning，整體 run 可為 partial；沒有 capture 的 legacy 寬鬆文字判定未修；upsert-only 不刪既有 closed-date bar／session；current raw `captured_at` 不是 official first availability／PIT；其他 endpoints 全走 legacy。一次相同 bytes 的 live capture 也不證完整年度 truth、revision lineage、長期 liveness 或 authenticity。本批不結清 R1-A1、R1-A3、C007／B5b、ATR strict calendar／halt provenance、公司行動、停復牌、完整 collector、正式 DB、排程或自動交易。

### 7.4 Round21 C021-C／D023-C today announcement code-only final review 證據

freeze 的 `backend/worker/sources.py` SHA-256 為 `0298d2604dd36a606b63d88d9946f8aac08eb418eda2528e20e30dade3919852`；`backend/tests/test_sources.py` 為 `0c13fa17f798cfd61bb01033833e298607805408438344cf2da87063209db752`；新增 `backend/tests/test_tpex_suspension_announcements.py` 為 `f61ed3789840b3b702a10da8183b16bcf9d7de313a23fae66984016197dd22f7`；既有 `backend/tests/test_stock_day_capture.py` 與 `backend/tests/test_holiday_capture.py` 分別為 `26e91393d481a758b419abc88dcfb8cdf16920a5303292a78b3a9b200d2cba66`、`fc69de0f1f67d222cab2d9ee6eb6d33c180151acb1361c541a4edbb4d1b103b1`。後兩檔只把各自 success／reuse fixture 的無關 today 回應設為空，原驗收 assertions 保留；非空公告導致 partial 的新行為另有專用測試。

作者 final targeted suite 為 177 passed、2,366 warnings，pytest 10.83 秒、process 11.938 秒、exit 0。統籌以 Python 3.12.14、Alembic 1.19.2 重跑完整 backend：696 passed、1 skipped、7,432 warnings，pytest 53.56 秒、process 54.610 秒、exit 0；106 個 code／tests／兩 DB guard 路徑的 SHA／size／mtime 全部 unchanged，四份本輪文件不在該 guard。唯一 skip 沿用既有 Windows symlink privilege 條件，本批沒有新增 skip。

統籌 independent final review 9／9 checks 通過：code-only、恢復、future suspension、malformed、未選取代號與 empty response 均經 actual `TpexAdapter`；恢復與 future-suspension 案例再經真 SQLite upsert／tracking。修正前同一重現為 `status=suspended`、`trigger=false`、`suspended=true`、`comparable=false`，修正後為 `active`、`true`、`false`、`true`；raw file SHA、integrity／FK、外部明確提供的 bar suspension flag 與六個 guard 路徑亦通過。這個 independent probe 不是 whole `collect`，也沒有獨立驗 ingestion-run linkage；完整 `collect`、raw linkage、force／failure 行為由作者 targeted tests 與統籌 full backend 覆蓋。它只獨立證 bar flag 與 tracking trigger／comparable；effective session、return 與 signal eligibility 只有既有程式的靜態 downstream path，沒有升格成獨立行為實證。

統籌第一次完整 backend 為 3 failed、693 passed、1 skipped、6,134 warnings，exit 1：兩個 holiday capture 與一個 stock-day capture 的舊 success／reuse fixture 誤帶非空 today 公告，因此依新契約正確成為 partial。只隔離該無關 fixture 後 final full 轉綠；失敗紀錄保留，不以重跑覆蓋。程式與統籌證據分別位於 `C:/Users/YiCheng/AppData/Local/Temp/stock-r21-c021-c-targeted-kwxkj8_9/` 及 `C:/Users/YiCheng/AppData/Local/Temp/stock-r21-coordinator-review/` 的 `full-backend-first-failed.log`、`full-backend-first-failed.json`、`full-backend.log`、`full-backend-review.json`、`independent-review.json`、`independent-review.log`。

本輪沒有新 live market request。官方證據只來自同一專案外目錄的 `official-catalog-evidence.json`／`tpex-swagger.json`：Swagger response 114,176 bytes、SHA-256 `47d4a6af0d7f19e735dfa42eefaa1e92a81f3f28a94b086ee8888dc81914ec34`，完整 JSON 因截斷不可解析，只有 today／history path 與各自 schema 四個 bounded object 可獨立解碼。它支持 endpoint identity／欄位區別，不支持完整 catalog、live payload、current-state truth、first availability、revision 或 PIT。`success + force=False` 仍是 zero-call reuse，不能修舊 flag；新 fetch 不自動重算舊 `SignalEvaluation`、不修其他日期，也不是 retroactive repair／replay。本批沒有新增 registry source、history capture loader、完整停復牌 coverage、正式 DB 修復或排程。

### 7.5 Round22 C022-B TPEx history identity 有限 review 證據

freeze 的 `backend/worker/sources.py` SHA-256 為 `4a94533a34f8e0433b7fced78fdc5bab33b53c970faadd43f40ba3651c43bc51`；新增 `backend/tests/test_tpex_suspension_identity.py` 為 `0b1881cdfc8bbdab5f23fc741d74ebdb916b67bfa3c484e4e8ac69fcbb01182a`。來源只刪除 `Serial` identity fallback 並加一行註解；新檔有 34 個 case：20 個 pure identity／audit、8 個 actual adapter（TPEx 與 both-market Official）、3 個 actual `collect`／migration-created SQLite raw linkage／gap／tracking、3 個 reuse／force refetch／legacy Event retention。測試全程禁網路。

作者 final targeted 為 97 passed、1,597 warnings，pytest 4.71 秒、process 5.5 秒、exit 0。統籌以 Python 3.12.14、既有 Alembic 1.19.2 重跑完整 backend：730 passed、1 skipped、8,093 warnings，pytest 55.53 秒、process 56.688 秒、exit 0；107 個 guard paths（其中兩個為正式與 `.local` DB）的 SHA／size／mtime_ns 全部 unchanged，四份 D024 文件不在該 guard。唯一 skip 沿用 Round18 Windows symlink privilege，沒有新增 skip。

統籌 independent review 15／15 checks 通過：10 個 actual `TpexAdapter` old／new raw、OHLC 與 identity 案例；4 個 old／new 真 SQLite pair 覆蓋 TPEx `7001`、TPEx `00679B` 與同代號 TWSE `7001` 的 exchange isolation、gap／tracking／comparable；另 1 個 legacy wrong Event 證明修正後 empty 結果不會刪除舊資料。這項獨立 review 不是 whole `collect`、沒有網路，且 DB 由 current `Base.metadata` 建立，不是 migration 驗收；actual both-market Official＋`collect`、raw FK、force／reuse 與 migration-created SQLite 是作者 34-case／targeted suite 及統籌 full backend 的證據，不能混寫成 15 checks 自己覆蓋。

官方欄位契約只依 `C:/Users/YiCheng/AppData/Local/Temp/stock-r21-coordinator-review/official-catalog-evidence.json` 與 `tpex-swagger.json` 的 bounded history path/schema object：完整 Swagger 在 114,176 bytes 截斷、SHA-256 `47d4a6af0d7f19e735dfa42eefaa1e92a81f3f28a94b086ee8888dc81914ec34`，不支持完整 catalog 或 live payload truth。程式證據位於 `C:/Users/YiCheng/AppData/Local/Temp/stock-r22-c022-investigation/`；統籌證據位於 `C:/Users/YiCheng/AppData/Local/Temp/stock-r22-coordinator-review/` 的 `independent-review.json`／`.log`、`full-backend-review.json`／`.log`。文件接受與輪末索引結果以本輪統籌 final receipt 為準。

### 7.6 Round23 C023-B／D025-B split-row linkage final review 證據

D025-A 外部契約、exact body、request metadata、獨立 oracle 與 freeze 位於 `C:/Users/YiCheng/AppData/Local/Temp/stock-r23-d025-contract/`。`D025-A-live-oracle.json` 對保存的 362-row body 得到 181 個唯一嚴格跨日 source pairs；`D025-A-oracle-tests.json` 是 9／9、exit 0 的**獨立仿寫契約／predicate oracle**，不是 actual worker consumer。統籌的 `live_shape_review.py`／`.json` 也是不 import production parser 的 offline 獨立 shape oracle；production old／new parser 對 181 pairs 的原序、反序與 seed 23 打亂驗證則屬 `independent_review.py` 的前三項 checks，兩者不得混稱。

C023-A2 把保存的完整 362-row body 送入 actual adapter，再由 synthetic universe 只選出 `1788` 的兩個 Event，並另以本地 fixtures 驗 `collect`／真 SQLite 邊界；這不能寫成 actual consumer 已處理全部 181 symbols。作者 C023-B 的嵌入式兩列 cases 才是直接使用 `1788` subset 的測試。官方 HTTP、independent shape、production parser、actual adapter 與 DB 證據歸屬必須分開。

freeze 的 `backend/worker/sources.py` SHA-256 為 `04872eb7ab86efdfadf80459bffc9a09db7a40aa358eae8b08e64ba5a731a178`；新增 `backend/tests/test_tpex_suspension_intervals.py` 為 `3a847b82ca7e52d19c478a261b0c08759b565c4309e86acd90253788f5344234`。作者新增 45 個 case；五個相關 module 的 final targeted 為 142 passed、1,846 warnings，pytest 5.24 秒、process 6.375 秒、shell wall 6.82 秒、exit 0。較早一次指定不存在的 `test_pipeline.py` 得 child／shell exit 4、no tests；這是命令路徑失敗，不是功能失敗，修正後上述 final suite 已通過。

統籌以 Python 3.12.14、Alembic 1.19.2 重跑完整 backend：775 passed、1 skipped、8,342 warnings，pytest 55.09 秒、process 56.281 秒、exit 0；唯一 skip 沿用 Round18 Windows symlink privilege。108 個 guard paths（106 個 code／tests／frontend 加正式與 `.local` 兩個 DB）的 SHA／size／mtime_ns 全部 unchanged，四份 D025-B 文件不在該 guard。統籌 independent 19／19 checks、exit 0：保存 body 在原序、反序與 seed 23 打亂下，各仍產 362 個原 audit Event，且只有 3 個 suspension details 欄位形成預期差異；12 類不合格 shape 維持舊行為；另驗 `Serial`／time raw-only、actual `TpexAdapter` 對 full saved body 的 synthetic universe 只選 `1788` 兩個 Event，以及 raw reserialization SHA、OHLC、warnings、coverage 不變。真 SQLite 以 current `Base.metadata` 建立三個 instrument，證同 Event key finite update、舊 evaluation 保留與新 evaluation active、integrity／FK 通過；這個 19-check review 不是 whole `collect`、不是 migration 驗收，且該路徑的 Event raw FK 為 null。actual `collect`、migration-created SQLite、raw FK／dedupe、reuse／force 與 evaluation 邊界另由作者 45-case suite 及完整 backend 覆蓋，不得混寫成 19 checks 自己覆蓋。

官方 HTTP 原 body SHA 只屬 D025-A direct GET；actual adapter 對 full body、fixture 或 subset 重新 JSON 序列化後的 raw SHA 必須依各自 log 歸屬。統籌證據位於 `C:/Users/YiCheng/AppData/Local/Temp/stock-r23-coordinator-review/` 的 `full_backend_review.py`、`full-backend.log`／`.json`、`independent_review.py`、`independent-review.log`／`.json`、`live_shape_review.py` 與 `live-shape-review.json`。

本輪仍未證完整 response headers、live whole-181 DB consumer、完整歷史、multiple cycles、active unmatched suspension、malformed／倒置／same-day 在官方 snapshot 的長期 occurrence、time/session 語意、first availability、revision、PIT、history capture consumer、完整停復牌 coverage、正式 DB 修復或排程。所有不符合唯一 split-pair 的形狀仍保留舊行為，可能留下無界 suspension 推定；這些是後續未完成項，不是本次有限 review 的擴張。

### 7.7 Round24 C024-B／D026-B 公司行動 mapping final review 證據

D026-A 外部契約、保存原 bytes／headers、逐 URL request metadata、獨立 oracle 與 proposal 位於 `C:/Users/YiCheng/AppData/Local/Temp/stock-r24-d026-contract/`。`capture-receipt.json` 記錄 7 次 direct GET，每一 URL 恰一次、零 retry／redirect、無 authentication、30 秒 client timeout、automatic decompression 關閉；全部當次 HTTP 200。這 7 次 raw captures 與另行使用的 web search／open discovery 必須分開計數。TWSE `TWT48U_ALL` body 為 18,203 bytes、68 rows、SHA-256 `a344e312b7809ad9fa1d2f949c39c6095bf0fd8dfcedd4e7bdbb8bb6ef51b907`，與 Round09 probe 相同；TPEx daily body 為 1,983 bytes、3 rows、SHA-256 `db1f6e359e2bf39dd2d202e35da147c6d44c5b3585ae5d41dbcbe80ceb190975`。兩份完整 Swagger 與兩份公式 HTML 的 bytes／hash／headers 皆在同一 receipt；這只證當次 liveness／shape／static notes，不證長期 schema、完整歷史、first availability、revision 或 PIT。

不 import production module、無網路的 `oracle.py`／`oracle-result.json` 為 17 passed、0 failed、exit 0：它重算七份 capture bytes／SHA、request accounting、Swagger descriptions、公式頁 static notes、TWSE／TPEx body shapes、三筆 actual cash-only component comparison，以及明確標為 official-schema-shaped synthetic 的 non-zero ratio 反例。它不是 actual adapter、`collect`、SQLite、feature 或 tracking consumer 驗收。`tpex_exright_prepost` 的 95-row current body另有 8 筆正 free ratio、3 筆正 paid ratio，但只是分離來源 shape，不得冒充 production `tpex_exright_daily` row 或已接 consumer。

C024-A 的 external wrapper／候選比較不是 final production mapping 證據；final production 證據來自 C024-B 實際 code／test 與統籌重跑。`backend/worker/sources.py` SHA-256 為 `8381ab59b4ddc462f354ccbab5642f2dd2c84b2b4b3a3cdf8f45a7886c0e0211`（105,402 bytes），新 `backend/tests/test_tpex_corporate_action_mapping.py` 為 `be1fd88112b560a17408693edc7b7e33ecd82869a9d5ca76ea87db05db2cb9a8`（14,678 bytes）。作者 dedicated 34 passed；新測試加 sources／pipeline integration 的 targeted 為 79 passed、1,094 warnings、pytest 3.32 秒（process 5.738915 秒）、exit 0，C024-B 沒有失敗測試嘗試。

統籌 independent review 為 26／26 checks、exit 0，且沒有失敗嘗試：涵蓋 old／new adapter method、保存的三列 body 兩種排列、future-as-of zero、隔離 2026-09-14 replay、migration SQLite 直接 `_upsert_action`、同 action ID 更新、舊 evaluation 在新 signal evaluation 後保留、兩個 consumer 的 `19/22` rational factor、交易所隔離、missing pre-close fallback、paid gap、integrity／FK 與 5-path guard。該 migration SQLite 路徑是直接 `_upsert_action` 且 `raw FK=None`，不是 whole `collect`／raw-FK／reuse-force 驗收；後三者的證據歸作者 C024-B 三個 integrations 與統籌完整 suite。完整 backend 為 809 passed、1 skipped、8,731 warnings、pytest 56.26 秒（process 57.5 秒）、exit 0；唯一 skip 是既有 Windows symlink privilege case。guard 實際核得 109 TOTAL＝107 個 source／code／tests／frontend paths＋2 個 DB，全部 unchanged，且不含 docs。統籌 log／JSON 位於 `C:/Users/YiCheng/AppData/Local/Temp/stock-r24-coordinator-review/independent-review.*`、`full-backend-review.json` 與 `full-backend.log`；作者交付位於 `C:/Users/YiCheng/AppData/Local/Temp/stock-r24-c024-investigation/`。

接受仍只證本輪具名的有效 cash／free、paid ratio 為零案例。cash precision precedence、invalid／negative／non-finite、missing reference fallback 的來源 truth、paid subscription、TWSE paid row、正式舊資料 repair、source admission／capture 與 PIT 仍屬未完成。既有同 key action 在有效 `force=True` refetch 時可以 upsert；`force=False` reuse 不更新。`collect` 不自動重算舊 evaluation，但顯式對同 signal 執行 evaluate 可能 upsert，因此也不能宣稱既存 evaluation immutable。

### 7.8 Round25 C025-B／D027-B cash precision final review 證據

C025-B 的 production diff 只有 `backend/worker/sources.py` 中 `TpexAdapter.fetch_actions` 的一行 cash key 順序；`backend/tests/test_tpex_corporate_action_mapping.py` 只把 R24 保存列的 cash 期待改為 0.26618165 並更新說明，R24 ratio/reference 與 paid-gap 測試保留；另新增 `backend/tests/test_tpex_cash_dividend_precision.py` 22 個 cases。final SHA-256 分別為 `7f6e91e881697ccc9ec0ddeef9224fff15144b3ac1d578f2b447f833844efe9f`、`642af878318e90eba1eb394b92a1f0da47e18e964db4c5c30b117b7319390a11`、`c87ecc935ffa26209b6cfa3fb9d787be78fb0e77603f126315723367d4077598`。R25 cash 契約取代 Round24 cash priority 的歷史保留，不改寫 Round24 當時的 34-case／79-pass ratio-reference 成果。

作者 final 四模組為 101 passed、1,236 warnings、pytest 3.88 秒（process 4.824 秒）、exit 0；初次 99 passed／2 failed／exit 1 已保留。第一個 failure 是 synthetic `'.26618165'` 被既有 substring parser 讀成 `26618165`，fixture 修成 official-shaped `'0.26618165'`，沒有改 parser；第二個是 tracking price 既有八位小數保存，測試 expectation 改用相同 round，factor 仍以 `rel=0, abs=1e-12` 驗證。這兩項修正都只改新測試，不是以 production 變更迎合失敗。

統籌完整 backend 為 831 passed、1 skipped、8,873 warnings、pytest 57.19 秒（process 58.391 秒）、exit 0；唯一 skip 是既有 Windows symlink privilege，沒有 full-suite failure。110 TOTAL guard＝108 個 code／tests／frontend source paths＋2 DB，全部 SHA／size／mtime_ns unchanged，docs 不在該 guard。統籌 independent 為 29／29 checks、exit 0，涵蓋 R25 baseline AST、新舊 selection 12 cases、原保存三列正反序、2026-09-13 future cutoff、tight Fraction、fresh 0006 migration SQLite、相同 action identity、兩個 consumer、舊 evaluation 保留、交易所／symbol isolation、既有 `MarketBar.close` fallback、integrity／FK 與 6-path guard；其 persistence 是 direct `_upsert_action(raw FK=None)`，whole `collect`／raw FK／raw bytes／zero-fetch reuse／force update 證據歸作者 integration。

D027-A standard-library `Decimal`／`Fraction` oracle 沒有 production import 或 network；作者 final 與統籌另跑均為 14／14、exit 0。統籌保存的 `d027-oracle-actual.json` 才是實際 stdout；D027 目錄的 `oracle-result.json` 明標 condensed summary。R25 新網路請求為 0；沿用的 TPEx daily 是 R24 在 2026-09-13 07:01:09 +08:00 的實際 request observation，`capture-receipt.json` 的 2026-09-12 23:04:24 UTC 則是 receipt generation，不得混稱。D027-A 的完整契約／報告位於 `C:/Users/YiCheng/AppData/Local/Temp/stock-r25-d027-contract/`；統籌證據位於 `C:/Users/YiCheng/AppData/Local/Temp/stock-r25-coordinator-review/`，作者交付位於 `C:/Users/YiCheng/AppData/Local/Temp/stock-r25-c025-investigation/`。

本批只接受 cash precision／selection。沒有新增 source admission／capture、quote rounding、paid factor、TWSE type/reference、generic numeric hardening、schema／execution version、正式 DB repair、舊 action／evaluation replay、historical availability／revision／PIT 或完整公司行動。新值下產生的 output 不宣稱可在未變更版本政策下重現既有舊 artifact；在 R25 驗收當時，正式／`.local` 兩個 DB baseline SHA 維持不變。其後正式 DB 的外部 preview 啟動變化見 §7.9，不回寫 R25 的歷史證據。

### 7.9 Round26 C026-B／D028-B TWSE source classification final review 證據

C026-B production diff 只有 `backend/app/api.py` 的純 helper 與 instrument detail additive 欄位，另新增 `backend/tests/test_twse_action_classification.py`；final SHA-256 分別為 `36118faed1e0b4ff6395b81c8e019847d9ea30449d057fbc7649f9e0ebb17735`（98,598 bytes）與 `529323a02db97feecdab288e0f77b0e080980854eef7d95525e300aafcea2a83`（14,356 bytes）。作者 final targeted 為 149 passed、335 warnings、pytest 2.19 秒（process 3.171 秒）、exit 0；初次 103 passed／1 failed 是同一 Session decision cache 使 query-count expectation 為 18／10，測試改用 fresh Session 後轉綠，production 未因此修改。

統籌獨立 129 checks、exit 0：35 個分類邊界、保存 68-row body、baseline AST 的 instrument-detail compatibility、三個 instruments／同日三種既有 type、舊／新均 19 queries（無新增 N+1）、50 筆上限與排序、所有 persisted fields 不變、既有 duplicate factor 不靜默修復、fresh 0006 SQLite integrity／FK 及 7-path guard。統籌完整 backend 為 935 passed、1 skipped、9,024 warnings、pytest 54.31 秒（process 55.453 秒）、exit 0；唯一 skip 是既有 Windows symlink privilege case。程式驗收報告位於 `C:/Users/YiCheng/AppData/Local/Temp/stock-r26-coordinator-review/FUNCTIONAL_ACCEPTANCE.md`。

D028-A 的 26／26 standard-library oracle 與完整契約位於 `C:/Users/YiCheng/AppData/Local/Temp/stock-r26-d028-contract/`；`D028-A-REPORT.md` SHA-256 為 `1c8f15a3654816645cae53f9dbac581b177228b80021f3e4d4e4f8fd20b708fb`，`oracle.py`／實際 `oracle-result.json` 為 `01cb6bb47c805e2e4c7a02cdcf5bad5deb01495e616f1d643c6b9b1ccc708728`／`18418fbe2f3be58de414df3c221d9fca497972b5be054132ff13960b8844575a`。oracle 不 import production、無網路、無 DB，故只作獨立契約邊界證據；actual adapter／API／SQLite 證據歸作者與統籌測試。

R26 round baseline 的正式 `data/stock.db` 是 296,054,784 bytes、SHA-256 `74a34389dbfa65429d27ea41bc9deca2a132808f10093e2ffde98665d96232d6`；輪初已知歷史狀態是沒有 `alembic_version`、有 fallback markers，不能稱原先 Alembic current 為 0001。另一個使用者 preview task `01a0994a-f42c-7f40-9aef-218d01917dab` 於 2026-09-13 啟動 `.venv` Uvicorn，其 lifespan startup log 顯示執行 `base→0001→…→0006`；這不是 C026／D028 寫入，也不是 R26 核准的 migration／repair。統籌其後只以 `mode=ro`／`query_only=1` 驗得 current `alembic_version=0006_news_json_defaults`、21 tables，查驗前後目前檔案仍為 296,366,080 bytes、SHA-256 `3a21772050b3053557c0798876cc0aa1efe024fcbdce5ab44e35e6abf12da018`；這不等於完整 historical/schema parity、正式 restore／deployment 或 migration acceptance。`.local/data/stock.db` 仍為 438,272 bytes、SHA-256 `87453d7b29954b6d506f8020b8987f321aa6749ce9bc24fbef695dd3874b8d02`。

本批只接受 read-only source classification projection。沒有新增 source admission／capture、raw-body membership validation、官方 identity／authenticity、TWSE reference／paid factor、worker／factor／schema／frontend、正式 DB repair、舊 action dedupe／evaluation replay、availability／revision／PIT 或完整公司行動。codebase-memory App 在文件 task 的輪初 coverage 可用；統籌 task 後續遇到 `Transport closed`，依專案既定方式改用相同引擎 CLI 作唯讀 coverage，沒有終止程序、改全域設定或中途更新索引；輪末索引仍歸 I065。

## 8. 有界 probe（非准入證據）

2026-09-12（臺北時間）對四個 exact endpoint 各做一次公開、唯讀 GET；完整 summary 在專案外 `C:/Users/YiCheng/AppData/Local/Temp/stock-r09-source-probes-d011/probes.json`。沒有重試、批量收集或 DB 寫入。

| endpoint | UTC observation | HTTP／shape | body SHA-256 | 僅能支持 |
| --- | --- | --- | --- | --- |
| `STOCK_DAY_ALL` | 2026-09-11T23:19:35.1474995Z | 200；JSON array 1,379；觀測列日期皆 ROC 1150911 | `0b1aff71084982ae31d719b47fff2c975205c6173ccb6d083232b4f5eeb23cbe` | 當次 liveness、content type、shape |
| `holidaySchedule` | 2026-09-11T23:19:35.4422178Z | 200；JSON array 27；觀測值 ROC 1150101–1151225 | `7644c1a8af784c09f54670fd7413f536b13eb76c54d658058e8873d1aee32117` | 同上；不是歷年 coverage |
| `TWT48U_ALL` | 2026-09-11T23:19:35.4497227Z | 200；JSON array 68；觀測值 ROC 1150910–1151028 | `a344e312b7809ad9fa1d2f949c39c6095bf0fd8dfcedd4e7bdbb8bb6ef51b907` | 同上；並顯示 current snapshot 可含未來預告 |
| `tpex_spendi_history` | 2026-09-11T23:19:35.4879861Z | 200；JSON array 362；含資料日、停／復牌日期時間欄 | `4e3747a4a27c1e45542ce476ff7ccd0384e5c420e9f2d5bbfd9257b9cc48e6a2` | 同上；不證完整歷史或 PIT |

web 擷取工具對 TPEx Swagger／terms 曾有 403／internal error，而相同官方 Swagger 可由直接唯讀文件請求取得；這是**查證工具通道差異**，不能寫成 endpoint 不可用。反之，四次 probe 的 HTTP 200 也不能證明長期可用、歷史完整、延遲、權利或 availability truth。

## 9. 後續 gate

1. Round19 已完成 §2.4 的 `twse_stock_day_all` selected-security bars 有限接線；Round20 再完成 §2.5 的 `holidaySchedule` positive exclusion。Round21 §2.6 修正 today announcement code-only 誤判，Round22 §2.7 修正 history parser 的 `Serial` 身分誤用，Round23 §2.8 再只補唯一嚴格跨日 split pair 的 resume linkage；Round24 §2.9 已通過 TPEx 公司行動 ratio／reference 兩欄 mapping，Round25 §2.10 再只修 cash precision／selection，Round26 §2.11 只增加 TWSE action 的 read-only source classification。這些資料品質批次都不是第三個 capture consumer。四個 Round09 source 中仍只有前兩個 domain 有具名有限 capture consumer；`TWT48U_ALL` capture／PIT、`tpex_spendi_history` capture 接線、完整 legacy collector、交易 session／TAIEX truth 與正式分類仍各自未完成。
2. `historical_pit` 必須取得逐筆 first-available、revision／withdrawal lineage 與可重建 snapshot 證據；只有今日 raw snapshot 或事件日期仍維持 unsupported。
3. 新增任何來源都重做逐用途查證；本批四來源外一律未審。
4. rate limit／發布時間查不到就保留 `unknown + reason`，必要時向官方窗口確認；不得用本地觀測值代替官方政策。
