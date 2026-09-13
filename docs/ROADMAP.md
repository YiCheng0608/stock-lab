# 開發路線、能力盤點與驗收

更新：2026-09-13。基線依原文件整理輪的程式靜態檢查與產品討論建立；其後 C-001 已完成 R0-2 最小信心語意相容修正並經統籌 review。Round12 C012 再完成分離的 `signal-artifact/v1` 純契約與明確 opt-in、專案外 immutable SQLite store 之有限 review；Round32 C032-B 又補上 `signal-comparison/v1` 有限 offline exact descriptive library。完整保存輸入的 paired replay、API／UI、worker、PIT 與 B7 仍未完成。Round13 依使用者決定先交付可操作的個股研究頁，具名有限範圍已通過統籌 final review；當輪延後的 signal comparison 現已由 Round32 只按有限 library 範圍接受，B7 仍保留。C-002 的 R0-1 第一段純 ATR 核心也已於 D-004a 修正後通過統籌 review。C-003 已完成 R0-5/B6 的正式 SQLite 唯讀現況與隔離副本／fresh DB migration review；在 C003 驗收時正式 DB 沒有升級。Round10 C010 再加入 synthetic 0004 pre-head regression 與隔離 SQLite restore mechanics，並揭露兩個 News JSON server-default gap；Round11 C011 已修正該兩欄，且在明列的 parity 與 atomic migration regression 範圍通過統籌 review。這只結清 R0-A2 的該項具名範圍，不宣稱所有 historical schema parity、正式 restore／deployment 或 R0 整體完成。Round 04 C-004 與 Round 06 C-006 已完成 B3-persist 的有限 review：schema 1 immutable store、`atr-provenance/v2` caller-provided strict 結構及同日 legacy＋兩 as-of 離線唯讀比較。Round07 C007 完成 B5a 的 `time-evidence/v1` 本地核心／專用 store／exact reader／JSON export；Round08 C008 再完成 `product-time/v1` 的既有 News、signal、action、stock、tracking API/UI read-time 相容投影。Round09 已完成 R1-A1／G-SOURCE 的版本化唯讀 registry foundation 與首批四個官方 endpoint 人工查證；Round18 C018 再完成相同四筆的顯式 opt-in、一次一來源 `source-capture/v1` standalone runtime；Round19 C019-B 只把已保存的 `twse_stock_day_all` 單日 bundle 接入既有 selected-security bar consumer；Round20 C020-B 再只把已保存的單年度 `twse_holiday_schedule` 接成多日 positive request exclusion；Round21 C021-C 又完成既有 `tpex_spendi_today` code-only 停牌誤判的有限修正，五個具名小批皆已通過各自有限 review。整體 R1-A1、完整 legacy collector gate、內容／時間 truth、PIT 與其他來源仍未完成。Round15／16 的 ordinary industry 與 Round17 ETF／new-listing candidate lifecycle 亦已在各自明列範圍通過 review，正式分類資料仍未修復。完整小批依賴與後續驗收見 [R0–R3 執行清單](ROADMAP_EXECUTION.md)，來源證據見 [SOURCE_REGISTRY](SOURCE_REGISTRY.md)，實作細節見 [R0 契約](R0_IMPLEMENTATION.md)。方向仍以 [產品規格](PRODUCT_SPEC.md) 為準，文件責任見 [索引](README.md)。

Round22 C022-B 再完成 `tpex_spendi_history` `Serial` 身分誤用的有限資料品質修正：官方 `SecuritiesCompanyCode` 與既有 local aliases 行為保留，只把 row number 移出 identity fallback。這不是 history capture consumer、舊 Event cleanup、PIT 或完整停復牌 coverage。

Round23 C023-B 再完成同一 history parser 的唯一嚴格跨日 split-row resume linkage 有限修正：只有 selected symbol 的全部輸入恰為一列 valid start-only 加一列 valid resume-only、兩列對側日期 raw text 都空白且 `start < resume`，才補 suspension interval end。其餘 shape 保留舊行為；這仍不是 history capture、完整 halt hardening、舊資料 repair 或 PIT。

Round24 C024-B 已通過 TPEx 公司行動兩欄 mapping 的有限 final review：只把「每仟股無償配股」正規化成每舊股 ratio，並把 `reference_price` 改為「除權息前收盤價」；不再誤用貨幣權值或開始交易基準價。paid-subscription、TWSE、capture／registry、PIT、舊資料自動 repair 與完整公司行動不在本批。

Round25 C025-B 已通過同一 TPEx action consumer 的 cash precision 有限 final review：只把 normalized `cash_dividend` 優先改為較精確的 exact `CashDivdend=現金股利`，再 fallback exact `CashDividend=息值` 與兩個 local compatibility labels。這項 R25 契約取代 Round24 當時保留的 cash precedence，不改寫 R24 ratio/reference 歷史成果；paid、TWSE、quote/tick rounding、capture／PIT、版本與舊資料 repair 仍未完成。

Round26 C026-B 已通過 TWSE 公司行動來源分類的有限 final review：只在 instrument detail 的既有 action rows 增加 read-only `source_action_classification`，不改 `type`／identity、worker、factor、raw、schema 或前端。另有使用者 preview task 的 API lifespan 將正式 DB 升到 0006；這不是 R26 migration／repair acceptance，且目前唯讀 head 查驗不等於完整 historical/schema parity。

Round27 C027-B 已通過 API startup readiness 的有限 final review：目前 checkout 的 lifespan 不再呼叫 `init_db`，只以唯讀 finite gate 檢查 marker 與必要 mapped schema identity；缺檔、版本或結構不合會 fail closed，schema 建立／升級仍須明確執行 `worker.cli init-db`。具名 R26 saved-original→current 外部 snapshots 已驗 20 個歷史表／622,399 rows preservation，另以外部副本 replay 0001→0006 後與 current 的 21 個 table descriptors、typed rows、完整 `sqlite_schema` 相同。這不接受正式 migration／restore／deployment、所有 historical／custom schema、非 SQLite、資料真實性或 PIT；也沒有重啟使用者既有服務。

Round28 C028-B 已通過 canonical legacy instruments `market/symbol → exchange/symbol` rebuild 的有限 SQLite rollback／fail-closed review。最終 222 個獨立 cases與 full backend `1,397 passed／1 skipped／12,029 warnings／exit 0` 通過，386 個新 parameterized cases已包含在 full run；96 個 injected faults全部 exact rollback後 same-DB retry成功。成功只涵蓋 finite canonical legacy與九個具名 application inbound FK，recognized current只作有限 identity no-rebuild；custom／reversed／mixed／missing／partial identity、scratch／TEMP shadow，以及已知 0002–0006 marker搭配 absent／legacy parent都拒絕且不自動 salvage。這不代表任意 historical／custom schema parity、non-SQLite、正式 migration／restore／deployment、資料 truth／PIT或R0完成。

Round29 C029-B 已通過 canonical legacy `signal_settlements` `UNIQUE(signal_id) → UNIQUE(signal_id, horizon)` rebuild 的有限 SQLite rollback／fail-closed review。最終 `408+14=422` 個 independent cases、統籌主矩陣 84 個 fault exact rollback／same-DB retry，以及 full backend `1,837 passed／1 skipped／12,414 warnings／exit 0` 通過；158 個 protected paths 維持不變。成功只涵蓋 unmarked exact known 9／14-column legacy、exact signals outbound FK 與 finite definitions；missing 或 NULL horizon 刻意 normalize 為 20。legacy inbound 與 unsupported custom schema 拒絕；recognized current 只作有限 essential-semantics no-rebuild，不等於任意 CHECK／trigger／extra schema 或 secondary nonunique index audit。R27 API startup readiness 在 R29 未修改，單一 external mixed-identity 重現仍會被 readiness 接受，列為下一輪候選；正式 migration／restore／deployment、資料 truth／PIT 與 R0 整體仍未完成。

Round30 C030-B 已接續補強 API startup 的 `signal_settlements` UNIQUE metadata gate：至少一個 ordered full ordinary BINARY ASC canonical pair，且所有 key parts 觸及 `signal_id`／`horizon` 的 UNIQUE 都必須是相同 pair；UNIQUE expression 保守拒絕。統籌以 87 個 populated external DB 的 261 個 direct／repeat／actual lifespan entries及261個memory INSERT probes驗收，final full backend為`1,963 passed／1 skipped／12,414 warnings／exit 0`，159 guards unchanged。identity分類只看key parts、不解析partial predicate；任意CHECK／trigger／unrelated UNIQUE不在audit，ASC／reverse是相容政策，通過也不保證任意INSERT。正式migration／repair／restore／deployment、資料truth／PIT與R0整體仍未完成；下一候選只有一個instruments mixed-identity external probe，尚無矩陣或結論。

Round31 C031-B 已把上述 instruments候選收斂成目前checkout的有限startup gate：mapped `market`／`exchange`／`symbol` 必須`hidden=0`，只作非hidden／generated相容檢查；canonical identity仍是ordered full BINARY ASC `UNIQUE(exchange,symbol)`。所有key parts觸及三欄的其他UNIQUE及任意UNIQUE expression都拒絕；key-unrelated named-column UNIQUE可包含generated extra／partial／collation／DESC，predicate與generated dependency不解析。DESC／reversed／superset等拒絕是policy而非必然collision，通過不保證完整writability或任意INSERT。統籌matrix為123 DB／369 entries＋492 memory probes，final full backend為`2,161 passed／1 skipped／12,414 warnings／exit 0`，160 guards unchanged。這不回寫R28 migration、不自動repair custom shape，也不代表正式migration／deployment、資料truth／PIT或R0完成；該輪交出的 R0-B2 offline comparison 候選已由 Round32 另行完成有限 review，不回寫成 R31 成果。

Round32 C032-B 已通過 `signal-comparison/v1` 有限 offline exact library review：caller 明示兩個專案外 absolute rollback-mode SQLite snapshots、兩個 expected SHA-256、opaque exact legacy key 與 conjunctive exact artifact selector；zero row 是 structured missing，invalid schema／data／FK／evidence／artifact integrity 則 hard fail。所有 dimension 最多是 descriptive，整體 `comparable=false`，沒有 delta、probability、winner、default、replay、availability 或 PIT claim。統籌 final matrix 58 cases／68 readonly connections／915 SQL statements、exit 0；review 作者 full backend 2,264 passed／2 skipped／12,414 warnings、exit 0及 162 guards；D034 另有 11／11 focused probes。完整 API 與限制見 [Signal comparison 契約](SIGNAL_COMPARISON.md)。下一候選只到完整保存輸入 replay 可行性調查；未預先核定實作，B2、B7、PIT、產品接線與預設切換仍未完成。

Round33 C033-B 已通過 caller-provided current pure-rule complete-argument capture/replay 的有限 library review：只支援兩個現行 evaluator，bundle exact 保存 admitted arguments／ordered histories／null、完整 config、recorded result，並綁 whole `domain.py` bytes、兩個 config digests、CPython 3.12.14／binary64。Replay 只比較 `passed/state/ordered reasons`；subject、market time、historical inputs、availability、PIT 與 full signal reconstruction 六項宣稱固定 false。作者 targeted 151 passed＝141 new＋10 domain、full 2405 passed／2 skipped／12414 warnings，兩個 run 均 exit 0 且各有 165 guards unchanged；統籌 82／82 與 25／25 matrices 各有 164 guards unchanged，亦均 exit 0。完整契約見 [Rule replay](RULE_REPLAY.md)。這不是 SignalArtifact／worker／API/UI／DecisionSummary 接線、historical recovery、legacy-v2 paired replay、B2 或 B7 完成。

## 1. 範圍與能力盤點

第一版暫定盤後決策、最早 T+1、數天至數週的股票研究。這是規劃假設，尚未確認精確持有期間、是否做空、風險預算或付費來源。現有 v1 為 long 策略，T+5／T+20 是追蹤窗口，不能直接當成必然出場日。

| 能力 | 2026-09-11 靜態核對 | 下一步 |
| --- | --- | --- |
| TWSE／TPEx 市場、法人／融資與 raw 稽核 | 有 adapter、收集及保存邏輯；資料完整性需逐域驗證 | 保留並補缺口，建立實際可用時間與修訂版本。 |
| 來源 registry／capture／既有 consumer | Round09 四來源 policy foundation、Round18 四來源 standalone `local_fetch + raw_store` executor、Round19 單一 `STOCK_DAY_ALL` 日期 selected-security、Round20 單年度 `holidaySchedule` 多日 positive exclusion、Round21 today-announcement code-only、Round22 history `Serial` identity、Round23 唯一嚴格跨日 split-pair linkage、Round24 TPEx 公司行動 ratio/reference、Round25 cash precision 及 Round26 TWSE read-only source classification 均已有限 review | 公司行動、停復牌 capture、完整 collector、session／PIT 仍分批驗收；Round21–26 都不外推成第三個 capture consumer。Round24／25 只改善 paid ratio 為零的具名有效 TPEx cash／free 事件；Round26 只分類已保存 TWSE details，不修 paid/reference、raw membership、舊 action／evaluation、來源准入或 PIT。 |
| backfill | CLI、scope、日期批次、重試與 coverage report 已存在 | 對照目前隔離驗收，不再當成未有指令。 |
| 官方新聞 | 有 Event → NewsItem、列表／詳情、時間品質與 keyset 排序 | 驗證邊界；加入新聞理解及經確認的外部來源。 |
| 國際／媒體新聞 | 主要收集流程未接入 | 來源選擇、使用條件及事件抽取。 |
| 官方產業／族群 | R15 mapping／隔離 diagnostic、R16 stock／ipo ordinary-industry 觀測期間與 R17 ETF／new-listing candidate lifecycle 已有限 review；正式 DB 仍有大量舊錯分類 | 保留前端 guard；正式分類修復依自身資料與驗收依賴決定，不綁定 Round19／20 的兩個 source consumer 小批，也不只為罕見 type switch 疊加 foundation。 |
| 當沖／借券／融券 | ChipSnapshot 有部分預留欄位；目前 ChipRecord 與 upsert 主要寫法人／融資 | 實際接入、驗證單位／日期／修訂，不把欄位存在當資料已存在。 |
| 分點及疑似隔日沖 | 檢查到的主要 worker 沒有分點收集或行為模型 | 先取得可重現歷史資料，再定義短線資金特徵。 |
| 技術與策略 | MA、量比、突破／回踩及規則價位已存在；新 ATR 純核心、B3-persist、B5a `time-evidence/v1` 本地 foundation／`product-time/v1` read-time 投影及 caller-provided current pure-rule replay 已有限 review，但仍未接入 worker／strict evidence | 下一步完成官方來源、strict evidence 與 B5b PIT 接線，建立 artifact/subject/time bridge，再做 legacy-v2 paired replay 及價位風險。 |
| 行動與持倉 | 有摘要聚合、壓縮卡、持倉新增／更新／刪除、張／股處理 | 回歸合併邊界；擴充完整交易計畫及曝險。 |
| AI | 主流程未見已訓練、經驗證的預測模型 | 分成新聞理解、量化評估、交易風險三部分。 |
| 追蹤／回測 | 有固定規則 replay、成本假設與 T+5／T+20 | 增加時間正確性、樣本外、模擬交易及功能增益比較。 |

靜態核對入口：[pipeline](../backend/worker/pipeline.py)、[sources](../backend/worker/sources.py)、[CLI](../backend/worker/cli.py)、[models](../backend/app/models.py)、[API](../backend/app/api.py)、[前端](../frontend/src/App.tsx)。未以本輪檢查宣稱上述能力已通過整體驗收。

### 1.1 Round13 個股研究整合（有限產品範圍已 review）

既有 `GET /stocks/{exchange}/{symbol}` 已回傳個股、最多 120 根正序 bars、族群、最多 120 筆籌碼、事件、策略條件、品質資料，以及 stock endpoint 追加的行動摘要與最多 20 筆 news。本輪開始時的頁面只有最近 30 根表格與最新 feature 數值，尚無可縮放 K 線；族群未呈現，且 news 被放在「官方事件」標題下。完整 API／畫面差異見 [個股研究頁契約](STOCK_RESEARCH_PAGE.md)。

本輪驗收聚焦：以真實 endpoint payload 顯示可縮放的日 K＋成交量、由本次 bars 計算且不足不補的 MA20／MA60、日期 OHLCV 提示、實際區間／來源與「原始 API 價格；還原方式未提供」，再把現有行動摘要、族群、法人籌碼、官方事件／新聞、策略條件與品質整理成一次可完成的研究流程。空值、無效 OHLC、重複日期與來源混合必須如實揭露，不以篩除或通用「官方來源」標籤掩蓋。

統籌已獨立重現資料轉換、前端測試／build 與隔離真實 API 瀏覽器流程，本節有限產品範圍改列 `已 review`。這不是 AI、PIT、ATR 換版、策略績效、個人化建議或完整交易計畫；R0-B2 comparison、R0-C5／B7 與原 R1–R3 缺口全部保留。完整證據與歷史錯誤揭露見 [個股研究頁契約](STOCK_RESEARCH_PAGE.md#51-2026-09-12-final-review-證據)。

### 1.2 Round14 全站前端 UX（已 review）

Round14 依既有 API payload 重整資訊密度、列表至詳情導流、台灣用語、資料日期、正負方向與 unknown 呈現。已知以股數提供的成交量與法人買賣超在使用者介面換算為張（1 張＝1,000 股，最多 3 位小數）；TWSE 融資交易單位在本輪台股介面顯示為張；來源或單位未知時不換算。族群詳情另須排除共用股票表格造成的錯誤「待補」別名、修正 `meta.data_as_of` 與相對 TAIEX 指標標籤，並恢復成員分頁。

統籌已以六個 self-test、32 項獨立檢查、typecheck／production build 與具名寬窄版瀏覽器流程通過本節的前端 UX 有限 review；輪末索引 receipt 亦已接受。逐頁證據、索引限制與未通過項見 [Round14 UX review](UX_REVIEW.md#5-final-review-證據與限制)。本批不新增後端、API units、DB、付費資料或來源接線，也不宣稱 8133 覆蓋頁真資料複驗、持倉實寫、產業分類或 ROADMAP 整體完成。

資料正確性優先後續項目已進入 Round15：官方 current 代碼表、shared 同義／market-only／停用／特殊碼與三種日期界線已收斂至 [產業分類契約](INDUSTRY_CLASSIFICATION.md)，程式修正與隔離 DB 診斷已通過統籌有限 review。正式 DB 目前仍保留舊分類且不得直接重算；Round14 的前端警示、mapping 測試或 counterfactual 副本均不能單獨結清正式資料修復。

### 1.3 Round15 產業分類修復（有限程式／隔離診斷已 review）

TWSE／TPEx shared current codes 沒有異義 collision；既有錯誤來自 TWSE 18、20–31 的 mapping 錯移、TPEx 已停用碼及特殊碼處理。統籌已在專案外 consistent copy 重現 2026-09-13 current-table diagnostic transition，並以同一 backup 建 2026-09-08 baseline／corrected pair：各 1,974 個 supported 標的都有唯一 expected membership，35 個 unknown／special 無一般產業 membership；current 舊 derived rows 保留，counterfactual 的輸入／歷史表等價，score rows 41→52、兩側各 6 個 non-null，隔離 signals 各 4,616 筆。正式與 `.local` DB 禁寫且未變，歷史分類無 evidence 不回填，前端 guard 不撤；證據、完整限制與來源 hashes 見 [產業分類契約](INDUSTRY_CLASSIFICATION.md#5-隔離驗收矩陣有限範圍已-review)。

### 1.4 Round16 ordinary-industry normal collector（有限接線已 review）

normal collector 現在只對 `stock`／`ipo` ordinary industry 使用 authoritative universe capture 的 `collected_at`，正規化成台北觀測日後做 forward-only period transition；上市日、行情 backfill 起日、score date 與 caller-provided `data_as_of` 不再當分類有效日。可信 numeric unknown／special／unsupported 會關舊不新增；missing／ambiguous evidence、same-day wrong、future／overlap period 或 canonical conflict 會整筆 rollback。`D > score_date` 只把 ordinary industry 標為 partial／skip，行情 run 可保持 success；成功 receipt、history、failed attempts 與去重 raw 的最早時間分開保存。新 raw 的 aware timestamp 先正規化成 UTC 再保存，既有 naive raw rows 不回寫。

統籌完整 backend 為 412 passed／4,902 warnings／pytest 31.67 秒／exit 0，並以實際兩市場 universe parser 加本地 official-shaped fixture 走完整 `collect`，11 項獨立檢查於 final 再次 exit 0；aware timestamp probe 亦通過，正式與 `.local` DB 未變。這不是 live 官方網路、來源時間真值、既有 legacy raw 時間修復、歷史 PIT、fresh 公司分類或正式資料修復；R15 guard 不撤。證據與欄位契約見 [產業分類契約 §6](INDUSTRY_CLASSIFICATION.md#6-round16-normal-collector-觀測期間有限接線已-review)。ETF／new-listing 日期與 lifecycle 後續另由 Round17 有限接線，不回頭擴大 R16。

### 1.5 Round17 ETF／new-listing candidate lifecycle（有限接線已 review）

normal collector 現在把 ETF category 與 new-listing 分成獨立 observation domain：ETF 的有限 category 是由官方 universe raw 經本地 `normalize_etf_category-v1` heuristic 推定，period 只自可信 capture 台北日 D 向前；new-listing 使用 authoritative listing date 的 0..60 個曆日 inclusive bounded period，與 IPO actionable 的 20／60 根有效 bars 分開。`D > score_date` 只 skip candidate mutation；future capture、缺失／非法 ETF category、期間或 canonical identity conflict 會 fail closed。authoritative ETF↔stock／IPO transition 只調整 ETF／new-listing domain，ordinary industry、manual、其他 hot group 與歷史 score 保留。

統籌 final 為 481 passed／5,066 warnings／pytest 49.91 秒（process 51.328 秒）、exit 0；實際兩市場 parser→本地 official-shaped fixtures→完整 `collect` 的 11 項檢查、SQLite physical transaction rollback probe、integrity／FK 及正式／`.local` DB 保護均通過。這只證 current capture 驅動的 candidate lifecycle；legacy 錯誤期間、synthetic index、bounded hot expiry conflict、caller-provided source truth、PIT、正式 DB／前端 guard、metadata history 無界與 ordinary-industry↔ETF 歷史轉換仍未完成。完整契約與證據見 [產業分類契約 §7](INDUSTRY_CLASSIFICATION.md#7-round17-etfnew-listing-candidate-lifecycle有限接線已-review)。

### 1.6 Round18 source registry runtime（有限 standalone capture 已 review）

`worker.source_runtime capture` 現在要求 manifest／profile／source／外部 version＋digest pins／專案外 output，並只接受 Round09 四個 exact GET endpoint。每次只送一個 GET，零 retry／redirect／warm-up；`local_fetch` 與 `raw_store` 都必須 allow，condition exact set、rate-limit fact 與 output preflight 不符時零 request fail closed。成功只以 exclusive hard-link 發布一個 `capture.zip`，保存 identity `body.bin` 與 `source-capture/v1` receipt；失敗沒有 output artifact 或 DB 寫入。

統籌 full backend 519 passed、1 skipped、5,066 warnings／exit 0，33 項獨立檢查通過，驗證期間納入 guard 的程式／測試來源與兩 DB unchanged。另一次真正 `twse_stock_day_all` CLI capture 為 1 request／HTTP 200／319,396 bytes／1,379 rows，bundle integrity 通過；這不是另外三筆 live 驗證、來源內容／時間 truth、PIT、完整 collector 或 R1-A1 結案。證據與限制見 [SOURCE_REGISTRY §7.1](SOURCE_REGISTRY.md#71-round18-c018-standalone-source-capture-final-review-證據)。

### 1.7 Round19 `STOCK_DAY_ALL` content／consumer（有限接線已 review）

`load_stock_day_capture(..., expected_market_date=...)` 會先重驗保存 bundle 的 exact members、receipt／pins／policy、全 body code／date 與 materialized files，再由 `TwseAdapter(stock_day_capture=...)` 把 capture date 的 selected-security rows 送進既有 `collect(..., force=True)`。missing／invalid selected symbols 不補 0、也不由同日 MI_INDEX security rows fallback；capture raw 保留原 SHA／aware UTC，但 `MarketBar.collected_at` 仍為 ingestion-now。這是 library-only opt-in，不是新增 CLI、all-offline 或 full-runtime gate。

統籌完整 backend 590 passed、1 skipped、5,198 warnings／exit 0，capture 30／30 與 existing-consumer 7／7 獨立 checks 通過；保存的 1,379-row bundle 得 1,367 個有效 rows／12 個 unavailable，實際 consumer 隔離結果為 partial、2 records、1 TAIEX record、10 raw payloads，並驗 exact-volume precision、舊 bar 保留、只有完整 `ingestion_run_id + source + endpoint + sha256` 相同才 raw reuse、session 不由 capture 單獨新增及 DB integrity／FK。沒有新 live，程式／測試與正式、`.local` DB fingerprints unchanged；完整證據與限制見 [SOURCE_REGISTRY §7.2](SOURCE_REGISTRY.md#72-round19-c019-b-stock_day_all-contentconsumer-final-review-證據)。本批不結清 R1-A1、C007／B5b／PIT、B7、summary、正式分類或另外三個 domain。

### 1.8 Round20 `holidaySchedule` positive exclusion（有限接線已 review）

Round20 把保存的單年度 `holidaySchedule` bundle 以 `load_holiday_capture(..., expected_schedule_year=...)` 完整驗 bundle／receipt／pins／hash／aware UTC time 與全 body date／weekday，再由 `TwseAdapter(holiday_capture=...)` 只替代多日 `fetch_bars` 的 holiday GET。closed 僅來自有限 holiday-name 加 exact `依規定放假1日。`、可重算一致的完整補假／多日句，以及 exact 市場無交易列；開始交易與 unknown wording 仍查 MI_INDEX。range 可跨年，但 capture 只排除自身年度的 explicit closed dates。calendar 本身不建立 bar、TAIEX、`no_data_dates`、session 或完整 coverage；未提供 capture 時 legacy 不變，顯式失敗不 fallback，同一成功 request key 仍須 `force=True` 才消費。collect upsert-only 也不會刪除或修正 DB 中既有 closed-date bar／session，因此本批不是 existing calendar consistency repair。

統籌完整 backend 為 678 passed、1 skipped、7,201 warnings，pytest 53.89 秒／process 55.016 秒、exit 0；final guard 的 code／source 與正式、`.local` 兩 DB fingerprints unchanged，文件不在該 guard。保存的 27-row live bundle manual oracle 為 24 closed／18 weekday closed／3 non-closure；final independent 17／17 checks 覆蓋五個 legacy delta、全域／文字／capture object timestamp drift、request list、真實 adapters／collect，隔離結果為 partial、26 records、13 TAIEX、48 raw，並驗 raw UTC／hash／reuse、closed 不新增 session 及 integrity／FK。作者 final holiday suite 為 88 passed；較早的作者 676-pass full 不是 final。這個 review 只證具名 positive request exclusion，不補全年 truth、first availability、revision、PIT、ATR strict calendar／halt provenance、公司行動或停復牌。契約與完整證據見 [SOURCE_REGISTRY §2.5](SOURCE_REGISTRY.md#25-round20-holidayschedule-positive-exclusion-接線有限內容既有-consumer-已-review) 及 [§7.3](SOURCE_REGISTRY.md#73-round20-c020-b-holidayschedule-contentconsumer-final-review-證據)。

### 1.9 Round21 TPEx today announcement code-only 修正（有限資料品質修正已 review）

本輪最小有用資料品質範圍不是新增完整停復牌 capture consumer，而是移除既有 `tpex_spendi_today`「只見證券代號即判 `end` 日停牌」的過度推論。官方 catalog 將 endpoint 定義為當日**公布**暫停／恢復交易股票，並同時提供暫停與恢復欄；非空 row 不是 current suspended-only truth。程式已保留 endpoint raw，非空公告只新增既有 warnings list 的純文字警告，不建立 reason-code schema；code-only row 不再覆寫正常 OHLC bar，空 response 也不證開市。統籌完整 backend 為 696 passed、1 skipped，independent actual-adapter／真 SQLite review 9／9 checks；history parser、tracking interval、future resumed schedule 與 PIT gate 不在本批改寫。詳見 [SOURCE_REGISTRY §2.6](SOURCE_REGISTRY.md#26-round21-tpex_spendi_today-code-only-停牌推論修正有限資料品質修正已-review) 與 [§7.4](SOURCE_REGISTRY.md#74-round21-c021-cd023-c-today-announcement-code-only-final-review-證據)。

### 1.10 Round22 TPEx history `Serial` 身分修正（有限資料品質修正已 review）

官方 bounded schema 將 `Serial` 定義為「編號」、`SecuritiesCompanyCode` 定義為「證券代號」；既有 history parser 卻讓 `Serial` 在 canonical 空白時先於 `Code`／中文 aliases 選為 symbol。最小修正只移除 `Serial` fallback，保留 `SecuritiesCompanyCode → Code → 證券代號 → 代號` 的 first-nonblank／allowed-universe 行為；後三者是 local compatibility，不冒稱 exact 官方 schema。Serial-only row 不再新增錯誤 Event，Code／中文 alias 不再被 Serial 遮蔽；canonical 非空 unknown 仍不 fallback，alias conflict、日期、intraday、future resume 與 PIT policy 不改。

作者新增 34 個 case，targeted 97 passed；統籌 independent actual-adapter／真 SQLite 15／15 checks、完整 backend 730 passed／1 skipped。真 consumer 證明新 Event 身分會改變 TPEx gap／tracking 且不污染同代號 TWSE；也證明 empty／Serial-only／另一證券的 force refetch 不會刪除舊錯 Event，故本批不是歷史修復。詳見 [SOURCE_REGISTRY §2.7](SOURCE_REGISTRY.md#27-round22-tpex-history-serial-身分修正有限資料品質修正已-review) 與 [§7.5](SOURCE_REGISTRY.md#75-round22-c022-b-tpex-history-identity-有限-review-證據)。

### 1.11 Round23 TPEx history split-row resume linkage（有限資料品質修正已 review）

同一 selected symbol 只有在**全部輸入恰為兩列**，且以既有 `_text(...)`／`parse_roc_date(...)` 判得一列 start 可解析而 resume raw text 空白、另一列 resume 可解析而 start raw text 空白，並滿足 `start < resume` 時，才把既有 `resumed_date`／`interval_end` 由 null 補為 resume date，另新增完整 `resumption_source_row`；原 `source_row` 仍是 start row，分開的 resumption Event 不變。invalid／空日期／duplicate 都算列數；identity aliases、coercion、row order、time raw、future cutoff、schema 與 gap predicate 均不改。

D025-A exact body 的 362 rows 形成 181 個唯一嚴格跨日 pairs；9／9 oracle 與統籌 `live_shape_review` 分別是獨立仿寫 predicate 與不 import production parser 的 offline shape oracle，production parser 的三種排列另屬 19-check independent review。actual adapter 對 full saved body 的 synthetic universe 只選 `1788` 兩個 Event，並非 live whole-181 DB consumer。作者相關 suite 142 passed；統籌 independent 19／19 與完整 backend 775 passed／1 skipped，guard 顯示 108 個 paths（106 個 code／tests／frontend 加兩 DB）unchanged。所有不合格 shape 沿用舊 row-local 行為，仍可能留下 `interval_end=null`／無界 tracking；`force=False` 可 reuse，`force=True` 可更新同 key Event，raw content 可 dedupe；舊錯身分 Event 不刪，既存 evaluation 不重算。詳見 [SOURCE_REGISTRY §2.8](SOURCE_REGISTRY.md#28-round23-tpex-history-split-row-resume-linkage有限資料品質修正已-review) 與 [§7.6](SOURCE_REGISTRY.md#76-round23-c023-bd025-b-split-row-linkage-final-review-證據)。

### 1.12 Round24 TPEx 公司行動欄位語意（有限資料品質修正已 review）

官方 exact schema 與計算頁證明，`tpex_exright_daily.StockDividend` 是以價格表示的「權值」，`OpeningReferencePrice` 是除權息後按檔位選取的「開始交易基準價」；兩者分別不能作 `stock_dividend_ratio` 與前收分母。C024-B 只改成 `StockDivdendThousandShares/1000` 與 `ClosePriceBeforeExRightsDiviend`，並移除原錯誤 aliases；missing reference 仍走既有 previous official bar fallback，其他 cash／identity／date／as-of／raw 行為不改。

在本輪具名正常輸入案例（finite `P>C≥0`、`Rf≥0`，且無 paid subscription 或其他同日調整）中，既有 factor `1/(1+Rf) × (P-C)/P` 與官方公式等價。完整公式另有現金增資認購價與配股率，現行 model／factor 未表示，故 paid subscription 仍未完成；也沒有新增 explicit quote factor、`tpex_exright_prepost` join、capture／PIT 或舊資料自動 repair／evaluation 自動 replay。D026-A 保存的 daily body 是三筆 ROC 1150914 cash-only future rows，2026-09-13 as-of 應得零；non-zero ratio 只用 official-schema-shaped synthetic 驗 conversion，不是 live。作者 dedicated 34／targeted 79 passed；統籌 independent 26／26、完整 backend 809 passed／1 skipped、109 TOTAL guard unchanged，均 exit 0。契約、完整 hash／warnings／timing與限制見 [SOURCE_REGISTRY §2.9](SOURCE_REGISTRY.md#29-round24-tpex-公司行動-ratioreference-mapping有限資料品質修正已-review) 及 [§7.7](SOURCE_REGISTRY.md#77-round24-c024-bd026-b-公司行動-mapping-final-review-證據)。

### 1.13 Round25 TPEx 公司行動 cash precision（有限資料品質修正已 review）

C025-B 只把 `cash_dividend` first-nonblank 改為 `CashDivdend` → `CashDividend` → `現金股利` → `息值`，沿用一次既有 `parse_number`；blank 才 fallback，nonblank invalid 不降級。保存 5278 從 0.266182 改取 0.26618165，cash-only factor 是 Fraction `472676367/478000000`；6204、8423 數值不變。相同 action identity、raw bytes／FK、date/type、free/reference、2026-09-13 future cutoff 與兩個 consumer 行為已在隔離 whole-collect／direct-upsert 證據中通過，但舊 evaluation 不會自動重算。

作者 final 四模組 101 passed；統籌 independent 29／29、完整 backend 831 passed／1 skipped，110 TOTAL guard unchanged，均 exit 0。R25 沒有新網路；仍沿用 R24 current snapshot，不證 historical availability／PIT 或官方 quote／tick 小數完全一致。Paid 仍缺可信 `Rp/S/P`、持久化與版本策略；schema/migration 只是可能設計之一。TWSE type-only 會產生第二 action 並雙算，checked TWT48U_ALL 也沒有 reference 欄；完整契約與證據見 [SOURCE_REGISTRY §2.10](SOURCE_REGISTRY.md#210-round25-tpex-公司行動-cash-precision有限資料品質修正已-review) 與 [§7.8](SOURCE_REGISTRY.md#78-round25-c025-bd027-b-cash-precision-final-review-證據)。

### 1.14 Round26 TWSE 公司行動來源分類（有限唯讀投影已 review）

C026-B 只在 `GET /instruments/{symbol}` 的既有 `corporate_actions[]` 增加 `source_action_classification`。source/exchange、exact `Code`／7 位 ASCII ROC `Date`／`Exdividend`、action identity 及 local aliases 全部一致時，`息`／`權`／`權息` 分別投影為 `ex_dividend`／`ex_right`／`ex_right_and_dividend`；其他 shape 一律 `unknown`＋固定 reason。既有 `type` 與 action identity 保留，故不會因 type-only 修正新增第二 action 或改 factor。

作者 targeted 149 passed；統籌 independent 129 checks、完整 backend 935 passed／1 skipped，舊／新 instrument detail 各 19 queries，均 exit 0。保存的 68-row current body 是息 63／權 2／權息 3；只證當次 shape，不證 stable event ID、raw membership、authenticity、availability／revision／PIT。worker、factor、raw、schema、frontend、舊資料 repair／dedupe 與 evaluation replay 均未改。完整契約、reason precedence、hash 與證據歸屬見 [SOURCE_REGISTRY §2.11](SOURCE_REGISTRY.md#211-round26-twse-source_action_classification有限唯讀投影已-review) 與 [§7.9](SOURCE_REGISTRY.md#79-round26-c026-bd028-b-twse-source-classification-final-review-證據)。

## 2. R0：修正研究基準與時間口徑（優先）

| ID | 狀態 | 已知問題／證據 | 要做的修正與驗收 |
| --- | --- | --- | --- |
| R0-1 | ATR 純核心與 B3-persist 已有限 review；B5a local foundation 與產品 projection 也已 review；B3-wire、B5b PIT、B7 與整體仍未完成 | worker `_calculate_features` 的 `atr14` 仍是最近最多 14 根 high-low 平均；另有已 review、未接線的 `technical_v2_atr14_wilder` 純核心與明確 opt-in schema 1 artifact store。C-006 新增 `atr-provenance/v2` strict writer/reader 與雙唯讀離線 compare；C007 的 time-evidence store 仍是獨立 local helper，兩者都未接 worker。 | [R0 §4.9](R0_IMPLEMENTATION.md#49-c-006-provenancecompatibility-final-review-與完成邊界) 已證明 B3-persist caller-provided provenance、schema 1 相容與 exact 離線比較；[R0 §7.1](R0_IMPLEMENTATION.md#71-round07-c007b5a-final-review有限本地-foundation) 與 [§7.2](R0_IMPLEMENTATION.md#72-round08-c008b5a-產品-read-time-projection有限-review) 分別證明時間角色 store 與產品 read-time 投影。下一步由 B3-wire／B5b 接官方 session、公司行動、availability truth、strict evidence 與 worker，最後做 B7 paired replay。不得覆寫 legacy、切換候選或把 caller fixture 當來源 truth。 |
| R0-2 | 最小相容修正、C012 local foundation、C032-B offline exact comparison 與 C033-B current pure-rule replay 已有限 review；B2 整體未完成 | legacy conditional 訊號可能保存固定 confidence=0.75；它不是校準機率。C012 新 store 與 legacy namespace 分離；Round32 只讀 caller 指定的兩個既存 snapshots；Round33 只 replay caller-provided current rule arguments，沒有 subject/time/source/availability 或 artifact linkage。 | C-001 已讓新 rule-only signal 寫 null並安全標示語意；C012 已驗 version binding／immutable lifecycle／reader/store，C032-B 已驗 descriptive comparison，C033-B 已驗 whole-source/config/runtime-bound current rule replay。仍未完成可證完整歷史輸入、SignalArtifact/worker bridge、legacy-v2 paired replay、API list/detail/action、DecisionSummary、前端、PIT 與 B7。詳見 [Signal artifact](SIGNAL_ARTIFACTS.md)、[Signal comparison](SIGNAL_COMPARISON.md)與[Rule replay](RULE_REPLAY.md)。 |
| R0-3 | B4a read-time 價位語意已 review；B4b 待實作 | `_risk_levels` 仍以固定風險距離計 `target_1=entry+1.6R`、`target_2=entry+3R`。C-005 新增 nested `signal-level-semantics/v1`，v1 數值與 legacy 列不變。 | signal full/compact/list/detail、action、stock detail、tracking 與 action/stock UI 已統一規則參考價；只允許 `breakout_v1@1.0.0`、`pullback_v1@1.0.0` canonical 推導，其他 identity fail-closed。新 trade plan、tick、gap、成本充分性、流動性仍屬 B4b。 |
| R0-4 | B5a local foundation 與產品 read-time projection 已有限 review；B5b 未完成 | signal.data_cutoff 寫 T 日 13:30；法人等資料未必在收盤時已公布。C007 已 review `time-evidence/v1` caller-provided store；C008 以 `product-time/v1` 在 News、signal、action、stock、tracking API/UI 明示角色與 unknown，但兩者沒有持久化關聯。 | 保留 C008 的 legacy 相容時間輸出；下一批仍須把官方 availability、C007 strict evidence 與產品／worker 接線並完成 B5b PIT gate。盤後資料只有這些驗收通過後，才能依實際可得時間支援隔日計畫。 |
| R0-5 | B6隔離升級、C010／C011具名migration regression、R27 startup readiness、R28／R29有限rebuild，以及R30 settlement與R31 instruments startup UNIQUE gate均已有限 review；外部preview已使正式DB到0006，但未通過正式migration驗收 | 程式單一head仍為`0006_news_json_defaults`。R28／R29只接受finite canonical migration shapes；R30／R31只補強startup metadata descriptor。R31把market列入target compatibility但不升格identity，並只對三個mapped target驗`hidden=0`；key-unrelated generated extra dependency、任意CHECK／trigger與任意INSERT仍不audit。 | API startup仍不自行migration。R31的123 DB／369 entries＋492 memory probes與full backend已通過；其strict startup policy可比R28 current no-rebuild更窄，`init-db`不會自動修所有拒絕shape。正式migration／restore／deployment、任意custom或所有historical schema、non-SQLite、auto salvage、資料truth／PIT與running service reload仍未完成。完整邊界見[R0 §8.10](R0_IMPLEMENTATION.md#810-round31-c031api-startup-instruments-unique-metadata-gate有限-review)。 |

C-001 沒有改策略 gate、價位、執行、歷史 DB 或 strategy version。統籌以 Python 3.12.14、`backend/.deps` 及隔離暫存 DB 完整執行 backend pytest：128 passed、4417 deprecation warnings、22.85 秒、exit 0。前端新增三個信心語意 assertions 已走到既存 pullback 文案 failure 前且通過，`pnpm build` 由程式 task 回報通過；原備份與目前 presentation test 都在同一既存 assertion exit 1，因此不能標示前端整套回歸通過。完整證據見 [R0 契約](R0_IMPLEMENTATION.md#52-c-001-實際相容行為與驗證)。

C-002 的純核心要求 `expected_sessions`、含 timezone 的 `decision_at`、公司行動全域 coverage／來源／可得時間，以及實際選用外部前收時的值／basis／來源／可得時間。公司行動清單是整個 artifact 共同比價基礎的 dependency manifest；任一 dependency 不合格就全 artifact fail-closed。停牌 assertion 只有在無價格 bar／全空 marker 時可跳過；與價格同時存在則 `suspension_price_conflict`。統籌 final targeted 為 28 passed、0.26 秒、exit 0，並以獨立手算驗證 Wilder 數值、future action 全 artifact fail-closed、as-of 不改舊 artifact，以及前收 precedence。C-002 另只修正既存 `presentation.test.ts` 過時期待，統籌編譯／完整執行該檔皆 exit 0；沒有改產品文字，也不等於全 frontend suite 或瀏覽器 UI 驗收。最後修正後未重跑完整 backend；153 passed／4417 warnings／23.92 秒是三項 targeted 修正前的歷史證據。詳見 [R0 契約](R0_IMPLEMENTATION.md#46-c-002-final-review-證據與未完成邊界)。

C-003 只修改 migration 測試契約，production migrations 未改。統籌在 2026-09-12 當時獨立確認正式 DB 以 SQLite `mode=ro`／`query_only` 讀取前後 hash、mtime、size 不變；它當時沒有 `alembic_version`，五筆 `schema_migrations` 不能當成 Alembic current。外部 Temp 的 consistent copy 與 fresh DB 都真正升到 0005；副本 20 個既有表（含 fallback marker 表）、622,399 筆 row count 及完整內容 fingerprint 保留，唯一新增 schema object 是 `alembic_version`。有 Alembic 的完整 backend 為 157 passed、4486 warnings、24.34 秒、exit 0；forward-only restore 未實跑。其後正式 DB 外部變化不回寫 C003 歷史。完整證據與環境限制見 [R0 §8.2](R0_IMPLEMENTATION.md#82-c-003-final-review-證據與限制)。

C010 只新增一個 migration test 與固定 SQL／JSON synthetic fixture；沒有 production/schema/frontend 或正式 DB 變更。統籌 full backend 為 241 passed、4613 warnings、31.69 秒、exit 0，另以不依賴 test helper 的六表全 schema／all rows 檢查完成 22／22；34 個 protected targets 無 hash／size／mtime 差異。真正 0004→0005 upgrade、五個 target columns、common-row preservation、constraints、second-upgrade idempotency、故障副本偵測與 consistent backup→新 Temp path restore mechanics 已有限 review；但 fresh 由 dynamic 0001/current metadata 建表時，`symbols_json`／`theme_ids_json` 缺少 0004 的 SQL `[]` defaults，raw omission insert 行為亦不同。故 schema parity 明確為 false，R0-A2 未結清；這不是正式庫 restore 或部署演練。完整證據與 hash 見 [R0 §8.3](R0_IMPLEMENTATION.md#83-round10-c010-migrationrestore-regression-assets有限-reviewr0-a2-未結清)。

C011 以 ORM SQL server defaults、`0006_news_json_defaults`、共用 SQLite repair helper、fallback 第六枚 marker 與 Alembic transaction 邊界修正上述兩欄差異。統籌完整 backend 為 259 passed、4625 warnings、14.12 秒、exit 0；獨立檢查為 73／73，atomic 矩陣為 24／24；32 個 protected targets 的 hash／size／mtime 不變。成功路徑涵蓋 fresh、old005、explicit 0004→0005→0006、Alembic／fallback 與 FK 0／1；24 組 fault 則明列 Alembic engine、Alembic external `Connection`、fallback 三入口，只對 fresh／old005 的各自 marker SQL 前／後故障驗完整回滾與 retry，不把 explicit 0004 說成完成全部 fault 交叉。可安全保存的自訂 index、owned trigger、default literal 與 self-FK 也已驗證；inbound FK、view、external trigger、AUTOINCREMENT、generated column、未知非空 default 等形狀會在 mutation 前拒絕，非 SQLite 未測。成功冪等只宣稱 schema、research rows 與 version set 不漂移；fallback operational `applied_at` 可更新。程式 head 當時已是 0006，但正式 DB 在 R11 驗收時仍沒有 Alembic current、只有五筆歷史 fallback markers；R26 的外部 preview startup 變化另案記錄，不回寫 R11 驗收。完整證據見 [R0 §8.4](R0_IMPLEMENTATION.md#84-round11-c011json-server-default-parity-與-atomic-migration-回歸有限-review)。

C028 Phase A 的57 cases／30 retries與統籌6-case probe保留舊0002 transaction破壞、lossy固定 rebuild及四個 false recoveries；FK0／1 after-DROP均由顯式 `foreign_key_check` 發現 orphan。Phase B最終只接受六個 code／test paths；source-freeze manifest SHA-256為 `3edb72132099cc746ea0309de1e9bbea62bf78f056ae0db123fd0906e877c0b5`。統籌 frozen matrix `206／206`、special `16／16`，共222 cases；full backend `1,397 passed／1 skipped／12,029 warnings`、pytest163.09秒／wrapper166.047秒、exit0，156 guards unchanged。作者run04的464 passed發生在最後marker patch前；final source的run05只是249-pass selected subset，final 386個新cases由統籌full run完整走過。News測試只有 `_old_005_engine` 的instruments `CREATE`／`INSERT`兩個fixture expressions改成完整current identity，其餘AST與News契約／assertions不變，不回寫R11。完整邊界與失敗史見 [R0 §8.7](R0_IMPLEMENTATION.md#87-round28-c028canonical-legacy-instruments-identity-rebuild-rollbackfail-closed有限-review)。

C029 Phase A 的修正前證據只證固定 settlement rebuild 會 lossy 或產生 false target claim，不是產品 pass；其 rollback envelope 在受測 fault 成立，也不代表成功契約正確。Phase B final 只改七個 code／test paths；artifact manifest SHA-256 為 `1fad7cc5d1874050d50f8658a8c35bc02b954a51bce7e6afaecc8b863526acbf`。統籌修正 matrix-01 自身 `signals` INSERT harness 錯誤後，matrix-02 `408／408` 與 special `14／14` 共 422 cases，主矩陣 84 faults 皆 exact rollback 後 same-DB retry；full backend `1,837 passed／1 skipped／12,414 warnings`、pytest 185.52 秒／wrapper 188.562 秒、exit 0，skip 為 Windows symlink privilege unavailable，158 guards unchanged。作者 targeted03 的 final 440 new settlement tests 另含 96 fault 與 144 false-marker cases；作者 full01 因外部 launcher 未向 child 傳 `PYTHONPATH` 而 1 failed，修正後只重跑 source-runtime targeted `38 passed／1 skipped`，失敗史不被 final success 抹去。News／recovery 只追加 empty prerequisites 與 loader adaptation，原 assertions 及 fixed SQL／JSON bytes 不變。完整邊界見 [R0 §8.8](R0_IMPLEMENTATION.md#88-round29-c029canonical-legacy-signal_settlements-identity-rebuild-rollbackfail-closed有限-review)。

C030 production 只改 `database_readiness.py`，新增一個 settlement UNIQUE helper與一個條件呼叫；另新增專用測試檔。作者 final targeted `664 passed／474 warnings／exit 0`涵蓋126個新tests；統籌final matrix為87個populated external DB、261個entries與261個memory probes，readonly trace／authorizer無business-row read，具名migration/helper/create_all bombs未觸發。final full backend `1,963 passed／1 skipped／12,414 warnings`、pytest226.12秒／process229.344秒、exit0；唯一skip為`backend/tests/test_source_runtime.py:238: symlink privilege unavailable`，159 guards的SHA／size／exactmtime unchanged。完整有限規則、source hashes與操作邊界見 [R0 §8.9](R0_IMPLEMENTATION.md#89-round30-c030api-startup-signal_settlements-unique-metadata-gate有限-review)。

C-004 新增獨立、明確 opt-in 的 SQLite artifact store；final `artifact_store.py`／test hash 為 `40CEC8F…`／`B519CF4F…`，ATR＋store targeted 47 passed，統籌完整 backend 為 176 passed、4486 warnings、26.84 秒、exit 0。獨立 fixture 驗證 store ownership、不可變 SQL、UTC retry、collision rollback、雙連線冪等與 final null／非負政策；legacy 程式與兩個研究 DB 基線不變。這只接受 caller-supplied metadata 的第一段有限儲存層；當時尚待的 strict provenance 與離線比較缺口已由 C-006 補齊。完整 C-004 證據見 [R0 §4.8](R0_IMPLEMENTATION.md#48-c-004-final-review-證據與未完成邊界)。

C-006 保留 schema 1 舊 payload/key/seal，新增 `atr-provenance/v2` strict writer/reader 與 legacy/artifact 雙唯讀 comparison。統籌完整 backend 為 200 passed、4592 warnings、25.72 秒、exit 0；獨立 fixture 驗 strict pre-commit rollback、C-004 bytes/seal 不變、同日兩 as-of 並存、相容 v2 delta 與 settings 不同時 pair-specific incomparable/delta=null，11 個保護檔不變。因此 B3-persist 只按 caller-provided 結構、隔離保存與離線比較的有限範圍完成；來源 truth、PIT execution gate、worker/API 與 B7 仍是 B3-wire／B5-time 後續。完整證據見 [R0 §4.9](R0_IMPLEMENTATION.md#49-c-006-provenancecompatibility-final-review-與完成邊界)。

C007 新增 `time-evidence/v1` 純 contract、專用 schema 1 local store、exact reader／lineage history、legacy-safe projection 與 JSON export。統籌完整 backend 為 215 passed、4592 warnings、24.03 秒、exit 0；專案外 22 項獨立檢查全過，15 個既有程式／DB 保護目標的 hash、size、mtime 全不變。這只完成 B5a 的 caller-provided 本地核心／儲存 foundation；`source_identity` 是 caller 選定 lineage key，各 role `source` 是證據提供者，均未經官方 truth 核驗。以 Round07 當時狀態，News/API/worker/UI、B5a 產品輸出、B5b PIT、正式 DB 與前端未接線／未驗；產品 read-time 缺口其後由 C008 補足，但 store-product persistence linkage 仍未做。完整證據見 [R0 §7.1](R0_IMPLEMENTATION.md#71-round07-c007b5a-final-review有限本地-foundation)。

C008 新增 `product-time/v1` read-time projection，覆蓋既有 News list/detail、signals、actions、stock directory/detail、dashboard 與 tracking 的 compact／nested 輸出；含 offset instant 正規化 UTC，date-only 不補午夜，naive／missing／不可信 basis/precision／News conflict 保持 unknown＋reason，response assembly time 與歷史 decision/generated 分開。前端以 Asia/Taipei 顯示已知 instant、純日曆顯示 date，已有 contract 的 unknown 不 fallback 舊日期。統籌 final backend 221 passed／4603 warnings／24.55 秒，四個 frontend self-test、跨 TZ presentation test、TypeScript 與 production build 通過；18 個 API response 在排除本次動態 `generated_at`／`response_generated_at` 後 legacy diff 為空，17 個入口 query count 相同，15 個保護目標不變。這只結清 B5a 的產品 read-time projection；沒有接 C007 strict store／worker、保存新時間、證明來源 truth 或執行 B5b PIT。完整契約與證據見 [R0 §7.2](R0_IMPLEMENTATION.md#72-round08-c008b5a-產品-read-time-projection有限-review)。

C012 的 final 四個 source/test hash 與 285-pass 完整 backend 證據見 [R0 §5.5](R0_IMPLEMENTATION.md#55-round12-c012-final-review-證據與未完成邊界)。保護目標結果是 40／41 unchanged：正式 DB 不變；唯一例外 `.local/data/stock.db` 可歸因於另一個服務 task 依使用者另行要求執行 lifespan `init_db`，不是 C012 寫入或 migration。故不得寫成全部保護檔不變，也不能把該外部 `.local` 變更納入 C012 驗收成果。

R0 不改 v1 名稱下的歷史規則定義；後續公式、gate 或執行修正仍需標記 feature／strategy／execution version、配置、資料快照和修正前後差異。R0-1 目前有已 review、未接線的純核心與有限 B3-persist；R0-2 有最小相容語意、C012 local foundation、C032-B 有限 offline exact comparison 與 C033-B caller-provided current pure-rule replay，但完整 historical／paired replay、產品、worker、PIT 尚未完成；R0-3 也只有 B4a read-time presentation semantics，R0-4 也只完成 B5a local foundation 與產品 read-time projection。C007 strict evidence 的產品／worker 關聯、B3-wire、B5b PIT 與 B7 尚未完成，不能據此宣稱整個 R0 已修復。

R0-3/B4a 的契約、入口矩陣與 final 證據見 [R0 §6.1](R0_IMPLEMENTATION.md#61-legacy-價位的強制標示)。統籌 full backend 為 180 passed；四個前端 self-executing test、production build 與專案外 fixture 的 action/stock 瀏覽器實驗通過，1/5 instruments 都是 13 queries 且無單獨 strategy query。Signal 仍沒有可採信的 legacy `decision_at`／price-basis identity：`data_cutoff`、date-only 欄位與 naive `created_at` 不提升成真實決策時間或 basis。C008 現在把這項 unknown 語意接到產品 API/UI，但仍未把 C007 strict evidence 接線。價位公式未扣成本；持倉 `average_cost`／使用者 stop、tracking `execution_price` 與規則參考價分開。signals/tracking UI 是 redirect，沒有冒稱獨立畫面驗收；fixture 也不是正式資料／真市場證據。B4b、B5b PIT 與整個 R0 仍未完成。

## 3. R1：可靠資料與事件研究

- 保留官方行情、TAIEX、法人／融資、公司行動、停牌和 raw provenance，依標的／日期／用途補資料。
- 新增來源 registry 與可用時間／修訂歷史；逐來源確認歷史範圍、費用、延遲、合法保存和摘要範圍。
- Round09 首批只查 `STOCK_DAY_ALL`、`holidaySchedule`、`TWT48U_ALL`、`tpex_spendi_history`。免費／OGL 1.0 支持附 machine-readable conditions 的本地擷取、raw 保存與摘要 policy eligibility；rate limit、精確發布時點、完整歷史、revision lineage 與 endpoint-specific deprecation 未查到者保留 unknown。四者都沒有足以准入 `historical_pit` 的證據；詳見 [SOURCE_REGISTRY](SOURCE_REGISTRY.md)。這是已 review 的局部唯讀 foundation，不是 R1 全域或 collector 接線完成。
- Round18 只為同四筆補上一次一來源的 `local_fetch + raw_store` standalone executor；Round19 再只為保存的單日 `STOCK_DAY_ALL` bundle 補 selected-security 內容驗證與既有 `collect` 的 library opt-in；Round20 又只為保存的單年度 `holidaySchedule` 補多日 positive request exclusion。Round21 修正 today-announcement code-only 停牌誤判；Round22 只移除 history parser 的 `Serial` fallback；Round23 再只補唯一嚴格跨日 split pair 的 resume linkage；Round24／25 分別修 TPEx 公司行動 ratio/reference 與 cash precision，均已有限 review。後五批都未新增 capture consumer；Round24／25 不補 paid subscription、TWSE type/reference、來源准入、歷史自動 repair 或 replay。完整公司行動／停復牌接線、完整 legacy collector、summary、官方 first availability、C007／B5b／PIT 與正式分類仍未接。
- 新聞產出事件群組、新資訊、影響對象、傳導理由、影響期間、反面證據及來源。
- 官方產業與跨產業題材分離；成員關係保留來源、生效日、關聯方法與版本。
- 接入當沖統計；若分點資料可取得，再建立集中度與次日反轉的描述特徵。尚無來源的功能保持不可用。
- 基本面先補支援公司品質與事件驗證的必要欄位，不先做完整財報分析產品。

驗收：重複轉載不重複算事件；歷史新聞不因新收錄而變最新；未知事件不補 0；當沖修訂值可按當時版本重放；不同交易所／股數／金額／日期不混用；題材多重歸屬不重複計入持倉曝險。新增資料不自動改變 v1 gate。

## 4. R2：候選與完整交易計畫

- 保留突破與回踩作比較基準，暫不大量增加指標。
- 題材看相對強弱、熱度增減、上漲擴散、領漲集中度、價格延伸與事件方向；原始數值、時間窗口、缺項分開呈現。
- 個股分開看公司品質、事件機會、交易位置、持倉風險；不先硬湊一個「好股分數」。
- 每一計畫定義決策時間、持有期間、觸發／確認方式、進場區间、不追價上限、失效／停損、目標／移動停利、時間停損與事件失效。
- 倉位考慮每筆可承受損失、單股及同題材曝險、已持倉與未成交計畫；未知風險預算時不給具體張數。
- 可輸出不交易、到期、未觸發、無法成交、資料待補；不以候選數量作績效。

驗收：每組價位能回推至同一策略／證據；跳空超過上限不追；同日觸及停損及停利無順序資料時不可比；成本後空間不足可拒絕；持倉風險優先；同一股票多題材／多策略不形成重複下單意圖。

## 5. R3：AI 與研究有效性

R1 的來源內文摘要可先在隔離環境驗證，無須等到預測模型；但不得將摘要流暢度當策略有效性。

1. LLM 提取與解釋可追溯事件，不直接產生無依據價位。保留模型／提示版本、輸入快照、引用、時間及更正紀錄。
2. 量化模型只預測事先定義的事件，例如「某持有期間內，先到目標而非停損的機率」，不能只寫「上漲機率」。
3. 訓練、校準與測試按時間分開；重疊持有期避免資訊洩漏，測試集不反覆調參。
4. 比較技術基準、加入族群、加入新聞、加入籌碼、加入 AI 的增量結果；控制同一 universe、資料窗口與成本。
5. 做 walk-forward、獨立樣本外及逐日保存決策的模擬交易。統計成本後報酬、回撤、成交率、有效樣本、尾部損失與機率校準。
6. 候選篩選及題材關係使用當時版本，包含下市／失敗標的，避免只看今天仍存在或已知熱門的股票。
7. 新聞歷史回測的 LLM 可能在預訓練中知道後續事件；僅限制提示日期不構成無洩漏證明。模型 cutoff 不明時，只作探索，另以模型定版後的前瞻模擬驗證。
8. 保留拒絕判斷、模型失效、資料漂移、來源停用及回退固定規則的路徑。

驗收標準與參數須在看測試結果前記錄。歷史跨度、樣本量與多種市場狀態都要評估；超過三個月不等於足夠。沒有證據時不顯示校準成功機率、不標示策略已採用。完整口徑見 [策略與驗證](STRATEGIES.md)。

## 6. 保留、降低優先與暫不做

| 決定 | 功能 |
| --- | --- |
| 保留且加強 | 來源追溯、品質／時間檢查、策略版本、回測、模擬追蹤、持倉風險、新聞、族群、個股頁。 |
| 保留於後台 | raw、ingestion run、coverage 明細、內部狀態／原因碼、完整公式。 |
| 降低新增開發優先 | 全 ETF 專用策略、完整財務記帳、大量技術指標、細碎呈現改版。現有資料／兼容能力不刪。 |
| 不納入第一版 | 盤中即時交易、自動下單、無來源的 AI 報價、未驗證勝率、確定身分的「隔日沖主力」標籤。 |

資料收集排程與交易自動化分開評估：前者需可靠來源、重試、可觀測性及操作設定；後者另需策略／執行驗證與明確授權。沒有理由要求收資料先證明策略績效；本輪兩者皆未啟動。

## 7. 待決定事項

| 決策 | 本文件暫定處理 |
| --- | --- |
| 持有期間、是否盤中／做空 | 暫以盤後 long、數天至數週設計；T+5／T+20 沿用作基準追蹤。 |
| 每筆與總體風險預算 | 不預填個人風險比例、不推具體張數。 |
| 新聞及分點來源、預算、歷史權限 | 先做來源可行性；不指定已採購供應商。 |
| AI 供應商、部署、成本／隱私 | 保留可替換介面；未選定、未接入。 |
| 預測目標、校準／採用門檻 | 建模前定義並記錄，不能看結果後調整成「通過」。 |
| 外部資訊審核 | 先採來源准入、逐項證據驗證及高風險／低把握人工覆核；不要求每則合格摘要一律人工點選。 |

## 8. 2026-09-11 原文件整理驗收

- 13 份原文件逐一處理；2 份新增文件為索引與本路線。
- 新能力全部標為待實作／待決定；舊 P0、測試與 Phase 作業均保留日期和範圍。
- 當時僅檢查文件連結、重複／過時狀態及程式對照；後續 C-001 的測試證據另記於 R0-2，不回寫成原文件整理輪已做過測試或策略驗證。
