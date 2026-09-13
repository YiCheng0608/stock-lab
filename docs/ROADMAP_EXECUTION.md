# ROADMAP R0–R3 執行清單

更新：2026-09-13。本文把 [ROADMAP](ROADMAP.md) 的 R0–R3 拆成可追蹤的小批；產品方向、能力狀態與優先順序仍以 ROADMAP 為唯一權威，R0 細節以 [R0 實作契約](R0_IMPLEMENTATION.md) 為準。Round12 C012 已新增 B2-persist 的有限本地 foundation，Round32 C032-B 再新增有限 offline exact comparison library，但 B2 整體仍未完成。Round13 的有限個股研究頁整合已通過統籌 final review；Round14 前端 UX 與輪末索引 receipt 已通過有限 review，見 [Round14 UX review](UX_REVIEW.md)。Round15 產業分類契約、程式與隔離 current／counterfactual 診斷、Round16 stock／ipo ordinary-industry normal collector 觀測期間、Round17 ETF／new-listing candidate lifecycle、Round18 四來源 standalone capture、Round19 單日 `STOCK_DAY_ALL` selected-security existing-consumer、Round20 單年度 `holidaySchedule` 多日 positive request exclusion，以及 Round21 `tpex_spendi_today` code-only 停牌誤判修正，均已通過統籌有限 review。正式資料仍未修復，完整 legacy source collector gate 仍未接。完整輸入 replay／B7 驗收保留。勾選單一批次不等於該 phase、整體研究或產品已完成。

Round22 C022-B 已通過 `tpex_spendi_history` `Serial` 身分誤用的有限資料品質 review；它沿用既有 history event consumer，只修 identity fallback，不新增 capture 接線、PIT 或舊資料 cleanup。

Round23 C023-B 已通過同一 history parser 的唯一嚴格跨日 split-row resume linkage 有限 review；它只替符合窄條件的 suspension details 補 interval end，不新增 capture、schema、其他 shape hardening、舊資料 replay 或 PIT。

Round24 C024-B 已通過 TPEx 公司行動兩欄 mapping 的有限 review：只把每仟股無償配股轉成每舊股 ratio，並以除權息前收盤價取代開始交易基準價作 reference；不補 paid subscription、TWSE、capture／registry、PIT 或舊 action／evaluation 自動 repair／replay。

Round25 C025-B 已通過同一 TPEx action consumer 的 cash precision 有限 review：只把 normalized `cash_dividend` 優先改成較精確的 exact `CashDivdend=現金股利`，再 fallback exact `CashDividend=息值` 與 local labels。這取代 Round24 當時保留的 cash precedence，不回頭改寫 Round24 ratio/reference 驗收，也不補 paid、TWSE、quote/tick rounding、capture／PIT、版本或舊資料 repair。

Round26 C026-B 已通過 TWSE action `source_action_classification` 的有限 read-only projection review：只在 instrument detail 增加 fail-closed 分類，不改既有 type／identity、worker、factor、raw、schema 或 frontend。另一個使用者 preview task 的 lifespan log 顯示對正式 DB 執行 `base→0001→…→0006`，目前 head 已唯讀確認為 0006；這不是 R26 migration／repair acceptance，也不證完整 historical/schema parity。

Round27 C027-B 已通過 API startup readiness 的有限 review：目前 checkout 的 lifespan 只做唯讀 finite marker／mapped-schema gate，不會自動建立、升級或修復 DB；明確 mutation 仍由 `worker.cli init-db` 與 worker 流程負責。readiness 本身不執行完整 integrity／row／data-FK scan；另一路具名 saved-original／current 20-table／622,399-row preservation 與外部 0001→0006 replay 對 current 的 21-table schema＋rows parity 已通過。正式 migration／restore／deployment、所有 historical／custom schema、非 SQLite、資料 truth／PIT 與既有 running service reload 仍未完成。

Round28 C028-B 已通過 R0-5 的另一個有限缺口：canonical legacy instruments identity rebuild 的 SQLite transaction／marker coupling、finite preservation及 fail-closed。222 個 independent cases、final full backend `1,397 passed／1 skipped／12,029 warnings／exit 0`與386個新 parameterized cases已由統籌接受。這不擴張R0-A2 News JSON defaults acceptance，也不把R27 readiness變成migration runner；完整範圍與證據見 [R0 §8.7](R0_IMPLEMENTATION.md#87-round28-c028canonical-legacy-instruments-identity-rebuild-rollbackfail-closed有限-review)。

Round29 C029-B 已通過 R0-5 的另一個有限缺口：canonical legacy `signal_settlements` identity rebuild 在 SQLite 三入口／FK 0／1 下的 finite preservation、marker coupling、rollback／retry 與 fail-closed。422 個 independent cases、統籌主矩陣 84 個 fault exact rollback／same-DB retry及 final full backend `1,837 passed／1 skipped／12,414 warnings／exit 0`由統籌接受。這不擴張 R0-A2 News JSON defaults acceptance，也不改 R27 API startup readiness；一個 external mixed-identity DB 仍可通過 readiness，僅列下一輪候選。完整契約與證據見 [R0 §8.8](R0_IMPLEMENTATION.md#88-round29-c029canonical-legacy-signal_settlements-identity-rebuild-rollbackfail-closed有限-review)。

Round30 C030-B 已接續完成該候選的有限 API startup 補強：`signal_settlements` 必須有 canonical ordered full ordinary BINARY ASC pair，所有 key parts 觸及 target 的 UNIQUE 都必須同形，UNIQUE expression 保守拒絕。87 個 populated external DB 的 261 個 direct／repeat／actual lifespan entries、261 個 memory INSERT probes與final full backend `1,963 passed／1 skipped／12,414 warnings／exit 0`已由統籌接受。identity分類只看keyparts、不解析partial predicate；任意CHECK／trigger／unrelated UNIQUE不在audit，ASC／reverse是policy，pass不保證任意INSERT。這不執行migration／repair，也不使R0完成；完整契約與證據見 [R0 §8.9](R0_IMPLEMENTATION.md#89-round30-c030api-startup-signal_settlements-unique-metadata-gate有限-review)。

Round31 C031-B 已完成另一個有限 API startup instruments gate：canonical identity仍是ordered `(exchange,symbol)`；`market`不是identity，但與exchange／symbol同為現行writer欄位及target-key compatibility範圍。mapped三欄須`table_xinfo.hidden=0`，target-key noncanonical UNIQUE與任意UNIQUE expression拒絕；key-unrelated named UNIQUE可含generated extra且dependency不解析。統籌123 DB／369 direct-repeat-lifespan entries＋492 memory probes、final full `2,161 passed／1 skipped／12,414 warnings／exit 0`與160 guards unchanged已驗。policy rejection不等於每個DESC／reversed／superset都必然collision，pass也不保證任意INSERT；完整契約見 [R0 §8.10](R0_IMPLEMENTATION.md#810-round31-c031api-startup-instruments-unique-metadata-gate有限-review)。當輪只交出 R0-B2 offline comparison 調查候選；Round32 另行接受其有限 library，不回寫成 R31 實作。

Round32 C032-B 已通過 `signal-comparison/v1` 有限 offline exact library review。兩個 explicit external rollback-mode snapshots、caller expected SHA、opaque exact legacy key 與 conjunctive exact artifact selector是唯一入口；missing sides 可診斷，其他 invalid schema／data／FK／evidence／integrity hard fail。所有 dimension 仍不證 input equivalence，`comparable=false`；沒有 CLI／API／UI／worker/default、replay、PIT 或 truth。統籌 matrix 58 cases／68 readonly connections／915 SQL statements、exit 0；作者 full 2,264 passed／2 skipped／12,414 warnings、exit 0由統籌 review，D034 focused 11／11。完整契約見 [Signal comparison](SIGNAL_COMPARISON.md)。下一候選只到完整保存輸入 replay 可行性調查，未預先授權實作。

Round33 C033-B 已通過 `rule-replay-bundle/v1`／`rule-replay-report/v1` 的有限 caller-provided current pure-rule library review。兩個現行 evaluator 的 exact complete arguments、whole ordered histories、explicit null、recorded result 與 whole-source/config/runtime binding 可 capture/replay；strict native JSON／digests／limits 與三個 typed error families已驗。作者 targeted 151 passed＝141 new＋10 domain、full 2405 passed／2 skipped／12414 warnings，兩個 run 均 exit 0 且各有 165 guards unchanged；統籌 82-case caller matrix 與 25-case binding/fault matrix 各有 164 guards unchanged，亦均 exit 0。它沒有 subject/time/source availability、SignalArtifact／worker／API/UI bridge、legacy evaluator、PIT 或 paired replay；完整契約見 [Rule replay](RULE_REPLAY.md)。

## 1. 執行界線與狀態

本清單固定採「免費公開資料與本地測試」：不採購資料、不使用付費 AI／資料商、不呼叫既有帳戶的付費額度，也不把帳戶、正式 DB、自動交易或正式排程視為一般開發授權。來源無法合法、穩定、可重現地取得時，該能力標為 `受限` 或 `不可用`，不以 fixture、欄位、模型介面、搜尋摘要或人工假資料冒充已接入。

| 狀態 | 可宣稱範圍 |
| --- | --- |
| `提案` | 契約存在，尚無對應程式／資料證據。 |
| `進行中` | 當輪 task 正在執行，尚未收到完整交付或通過 review。 |
| `已實作` | 變更存在且有執行證據，尚未由統籌獨立重現。 |
| `已 review` | 統籌已重現本批驗收；只代表該批明列範圍。 |
| `等待` | 必須等待來源、時間跨度、樣本累積或已列出的決策。 |
| `受限` | 免費公開來源或 point-in-time 證據不足；功能維持不可用／探索用途。 |

每批證據至少記錄：日期與 reviewer、工作樹檔案雜湊或 commit、設定與資料 snapshot、具名隔離路徑、完整命令與 exit code、通過／失敗／跳過數、schema／row 影響、已知限制。只有 fixture 或 mock 的測試必須明寫「介面／失敗行為驗證」，不得寫成實際來源、全市場 coverage、策略有效或前瞻研究通過。

### 1.1 Round13／個股研究頁

| 狀態 | 依賴與輸入 | 本批完成條件 | 不在本批 |
| --- | --- | --- | --- |
| `已 review`（有限個股頁整合） | 既有 `GET /stocks/{exchange}/{symbol}` 真實 payload；前端既有 ECharts 依賴；不改 backend、worker、DB、package 或 lockfile。 | 日 K／量、MA20／MA60、研究區塊與負面狀態已由統籌以具名測試、build 及隔離真實 API browser 流程獨立重現；完整證據見 [個股研究頁契約](STOCK_RESEARCH_PAGE.md#51-2026-09-12-final-review-證據)。 | 新 AI／評分、外資身分推論、策略績效、PIT、ATR 切換、新 trade plan、完整歷史、正式或 `.local` DB 寫入。R0-B2 comparison 與 R0-C5／B7 延後但不刪除。 |

欄位、資料轉換、可及性、負面案例與 final review 證據的單一契約見 [個股研究頁契約](STOCK_RESEARCH_PAGE.md)。本列的 `已 review` 來自統籌獨立重現，不是以程式或 screenshot 存在逕自結案。

### 1.2 Round14／全站 UX

| 狀態 | 依賴與輸入 | 本批完成條件 | 不在本批 |
| --- | --- | --- | --- |
| `已 review`（前端 UX；索引 receipt 已接受） | 既有前端路由與 API payload；Round13 個股頁基線；使用者指定台股顯示單位與用語。 | 列表／詳情、上一頁／下一頁／儲存／庫存、張數與正負方向、unknown fail closed、族群欄位別名／日期／分頁及舊分類警示已由統籌以六個 self-test、32 項獨立檢查、typecheck／build 與具名瀏覽器流程核對；完整證據見 [Round14 UX review](UX_REVIEW.md#5-final-review-證據與限制)。 | 新增 API `units`、後端／worker／DB 工程、來源接線、產業分類資料修復、8133 覆蓋頁真資料複驗、持倉實寫、策略／研究評分或付費服務。警示不代表分類、分數或正式 DB 已修復。 |

本批細節只以 [Round14 UX review](UX_REVIEW.md) 的逐頁矩陣、單位表及 final review 證據為準；`已 review` 只適用於其具名的前端 UX 範圍。輪末索引已接受，但 backend exact coverage 的 `metadata_changed` 限制仍保留。

後續資料批次依賴官方 TWSE／TPEx 代碼表、已 review 的市場別 mapping 與隔離診斷；來源及邊界見 [產業分類契約](INDUSTRY_CLASSIFICATION.md)。本批不寫正式 DB，也不以隔離通過或 Round14 warning 結清正式資料修復。

### 1.3 Round15／產業分類 current-table diagnostic

| 狀態 | 依賴與輸入 | 本批完成條件 | 不在本批 |
| --- | --- | --- | --- |
| `已 review`（有限程式／隔離診斷） | 2026-09-13 官方 code-table evidence；正式 DB consistent read-only backup；`market_data_as_of=2026-09-08`。 | 完整 mapping 正／負測試；current 隔離副本的 forward-only membership period；原 2026-09-08 derived rows 不變；同 backup 的 baseline／corrected counterfactual scores 與獨立 namespace signals。統籌獨立核對 SQL／表／均值、integrity、FK、trace 及正式／`.local` DB 不變；模型第二次 rerun 由作者執行，統籌 review 程式與 final report。 | fresh 公司分類 truth、歷史 PIT／有效日回填、正式 DB 寫入、舊 signals／tracking 覆寫、策略有效性、解除前端 guard。 |

`classification_evidence_at`、`membership_effective_date` 與 `market_data_as_of` 必須分開；2026-09-13 只是本輪 current-table diagnostic 的切換日。完整市場別 code 表、停用／特殊碼與驗收矩陣見 [產業分類契約](INDUSTRY_CLASSIFICATION.md)。

統籌獨立重現：current／counterfactual 各 1,974 個 supported 標的皆為唯一 expected membership，35 個 unknown／special 無一般產業 membership；關閉 1,551、增加 1,541，原 2,403 筆 membership 保留。baseline／corrected score rows 為 41／52、各 6 個 non-null，兩側隔離 signals 各 4,616 筆；完整 backend 372 passed、exit 0，integrity／FK 與正式／`.local` DB 不變均通過。這是 current-table counterfactual 診斷，不是 PIT、策略有效性或正式修復。

### 1.4 Round16／ordinary-industry normal collector

| 狀態 | 依賴與輸入 | 本批完成條件 | 不在本批 |
| --- | --- | --- | --- |
| `已 review`（有限 normal collector 接線） | R15 current code mapping；TWSE／TPEx authoritative universe capture；只處理 `stock`／`ipo` ordinary industry。 | 按本次 capture 台北觀測日 forward transition；numeric unknown／special／unsupported 關舊不新增；missing／ambiguous、same-day、future／overlap、identity conflict atomic fail；`D > score_date` partial／skip；receipt/history/failed-attempt/raw-time 分離；新 raw aware timestamp 先正規化為 UTC。統籌完整 backend 412 passed、獨立 actual-parser→collect 11 checks、aware probe、integrity／FK 與正式／`.local` DB 保護均通過。 | live 官方網路與 capture metadata 外部真值、historical PIT／source effective date、既有 naive raw 時間修復、ETF／new-listing 期間、正式 DB 修復、所有表重跑不變、舊 derived 重算、guard 解除。 |

完整欄位、失敗 raw 保存差異與證據見 [產業分類契約 §6](INDUSTRY_CLASSIFICATION.md#6-round16-normal-collector-觀測期間有限接線已-review)。ETF／new-listing 日期與跨 domain lifecycle 後續另由 Round17 有限接線；不由本列回頭擴大 R16。

### 1.5 Round17／ETF 與 new-listing candidate lifecycle

| 狀態 | 依賴與輸入 | 本批完成條件 | 不在本批 |
| --- | --- | --- | --- |
| `已 review`（有限 candidate lifecycle 接線） | R16 current capture／raw receipt 基線；TWSE／TPEx authoritative universe parser；本地 official-shaped fixtures；SQLite caller transaction。 | ETF local heuristic 與 raw provenance 分離、category period 自 D forward；new-listing 上市事件窗口為 `L..L+60`，新 membership 僅在 `L <= D <= L+60` 時建立為 `[D, L+60]`；20／60 effective bars 另屬 actionable guard；`D > score_date` skip、future capture／evidence conflict及已有 history 的 prospective L fail-closed、missing L unresolved、無 history 的 prospective L 不預建；ETF↔stock／IPO domain-isolated transition；receipt 子 scope 與 SQLite savepoint／outer rollback。統籌完整 backend 481 passed、actual-parser→collect 11 checks、physical transaction probe、integrity／FK 與正式／`.local` DB 保護均通過。 | live source／capture metadata 外部真值、ETF heuristic 品質、legacy 錯誤期間修復、synthetic index lifecycle、bounded hot expiry conflict 自動修復、historical PIT／source effective date、ordinary-industry↔ETF 歷史轉換、正式 DB／guard、metadata history 長期治理。 |

具名日期、receipt、atomicity、final 證據與限制見 [產業分類契約 §7](INDUSTRY_CLASSIFICATION.md#7-round17-etfnew-listing-candidate-lifecycle有限接線已-review)。該段當時的「下一輪」已在 Round18 選定 source runtime 小批；這不回頭擴大 R17，也不只為罕見 type switch 增加 foundation。

### 1.6 Round18／source registry standalone capture

| 狀態 | 依賴與輸入 | 本批完成條件 | 不在本批 |
| --- | --- | --- | --- |
| `已 review`（有限 standalone capture） | Round09 `source-registry/v1`／`source-policy/v1`、四個 exact GET endpoint、外部 version＋digest pin、專案外新／空 output。 | `worker.source_runtime capture` 對單一來源先驗 `local_fetch + raw_store` allow 與 exact conditions，再以 1 GET／零 retry、redirect、warm-up、5 MiB／15 秒 per-operation／30 秒 cooperative 界線擷取 identity body；單一 `capture.zip` exclusive publication、receipt attribution／hash／aware UTC／rate-limit facts、失敗零 artifact／no DB。統籌 full backend 519 passed＋1 skipped、獨立 33 checks 與一次 `twse_stock_day_all` live CLI 已通過。 | 另外三筆 live 可用性、來源內容／時間 truth、legacy collector gate、summary、historical PIT／strict evidence、正式 DB、排程與其他來源。 |

完整 CLI、bundle／failure 行為、hash、live 證據與 symlink skip 限制見 [來源 registry §7.1](SOURCE_REGISTRY.md#71-round18-c018-standalone-source-capture-final-review-證據)。Round19 已選定並完成下節的單日 `STOCK_DAY_ALL` selected-security 小批；不回頭擴大 Round18。

### 1.7 Round19／`STOCK_DAY_ALL` content 與 existing consumer

| 狀態 | 依賴與輸入 | 本批完成條件 | 不在本批 |
| --- | --- | --- | --- |
| `已 review`（有限內容／既有 consumer 接線） | Round09 pins／policy；Round18 已保存的單日 `twse_stock_day_all` bundle；專案外 materialization／DB／raw；caller 明列 market date 與 symbols。 | `load_stock_day_capture(..., expected_market_date=...)` 先驗 ZIP／receipt／pins 與全 body container／code／date，成功 materialize 後才回傳 object；`TwseAdapter(stock_day_capture=...)` 的 `fetch_bars(...)` 呼叫 `capture.select(...)`，再驗 selected OHLC／精確 volume／turnover，並接真實 `OfficialMarketDataAdapter`／`collect(..., force=True)`。同日 capture rows 不准 MI_INDEX security fallback，raw SHA／UTC／refs 保留；missing／invalid 留 warning，依既有整體結果可為 partial，另有 fatal condition 則 failed。capture 不單獨建立 session。統籌 full backend 590 passed＋1 skipped、capture 30 checks、existing-consumer 7 checks 與精度 probe 通過。 | 新 CLI、all-offline／full-runtime gate、新 live、另外三 domain、兩市場完整 parser、published／first-available／revision truth、C007／B5b／PIT、summary、正式分類／DB／排程；舊 bar 與 `adj_close` fallback 仍保留。 |

完整 API、materialization／raw dedup 邊界、hash、1,379 rows→1,367 個有效 rows＋12 個 unavailable、隔離 consumer 結果與限制見 [來源 registry §7.2](SOURCE_REGISTRY.md#72-round19-c019-b-stock_day_all-contentconsumer-final-review-證據)。Round20 後續已完成下節的單年度 `holidaySchedule` positive request exclusion；這不回頭擴大 Round19，也不代表一次接完四域。

### 1.8 Round20／`holidaySchedule` positive request exclusion

| 狀態 | 依賴與輸入 | 本批完成條件 | 不在本批 |
| --- | --- | --- | --- |
| `已 review`（有限內容／既有 consumer 接線） | Round09 pins／policy；Round18 runtime；單年度 `twse_holiday_schedule` bundle；caller 明列 expected schedule year、專案外 materialization／DB／raw、既有 TWSE／TPEx ancillary feeds。 | `load_holiday_capture(...)` 驗 ZIP／receipt／pins／hash／aware UTC 及全 body unique date／weekday；窄 grammar 只產 explicit closed dates。`TwseAdapter(holiday_capture=...)` 僅替代多日 holiday GET，closed weekday 不送 MI_INDEX；跨年其他日期、unknown wording 仍查。calendar 本身不建 bar／TAIEX／no-data／session；可見有效 daily security／current index 與 closed 衝突 fail closed；raw SHA／UTC／refs、legacy no-capture、`force=True` 與 reuse 行為可重現。collect upsert-only 不修正既有 closed-date bar／session。統籌 full backend 678 passed＋1 skipped、final independent 17 checks 與 code／DB guard 通過。 | 單日 holiday path、完整交易日曆／open-session coverage、既有 calendar consistency repair、未抓 MI_INDEX 的內容驗證、歷年 archive、published／first-available／revision／PIT、C007／B5b、ATR strict calendar／halt provenance、公司行動、停復牌、完整 collector、排程／正式 DB。 |

一次真正 R18 runtime holiday GET 為 HTTP 200、3,774 bytes、27 rows、SHA-256 `7644c1a8af784c09f54670fd7413f536b13eb76c54d658058e8873d1aee32117`。統籌完整 backend 為 678 passed、1 skipped、7,201 warnings，pytest 53.89 秒／process 55.016 秒、exit 0；final independent 17／17 checks 的 manual oracle 為 24 closed／18 weekday closed／3 non-closure，真實 adapter／collect 隔離結果為 partial、26 records、13 TAIEX、48 raw，且 code／source 與兩 DB guard 通過。作者 final holiday suite 為 88 passed；較早作者 676-pass full 不是 final。契約、證據位置與限制見 [來源 registry §2.5](SOURCE_REGISTRY.md#25-round20-holidayschedule-positive-exclusion-接線有限內容既有-consumer-已-review) 與 [§7.3](SOURCE_REGISTRY.md#73-round20-c020-b-holidayschedule-contentconsumer-final-review-證據)。

### 1.9 Round21／TPEx today announcement code-only 修正

| 狀態 | 依賴與輸入 | 本批完成條件 | 不在本批 |
| --- | --- | --- | --- |
| `已 review`（有限資料品質修正） | 既有 `TpexAdapter.fetch`、`tpex_spendi_today` raw audit、`MarketBar.is_suspended` 下游；官方 today/history path 與 schema bounded catalog evidence。 | 不再由 today row 的證券代號存在單獨覆寫正常 `end` 日 OHLC；非空公告保留 raw 與既有 warnings list 純文字警告、空列不證 open。作者 targeted 177 passed；統籌 full backend 696 passed＋1 skipped、independent actual-adapter／真 SQLite 9／9 checks，並證 tracking trigger／comparable、raw／integrity／FK 與 106 個 code／tests／兩 DB guard 路徑。 | 新 reason-code schema、effective-session／return／signal eligibility 獨立實證、新來源／第五 registry row、`tpex_spendi_history` capture loader、history parser／tracking interval 重寫、future resume blanket filter、official first availability／revision／PIT、完整停復牌 coverage、retroactive repair／replay、正式 DB 修復、排程。 |

完整時間角色、future resumed schedule 判定、force／reuse 邊界、截斷 Swagger 證據限制及失敗後轉綠的 final 證據見 [來源 registry §2.6](SOURCE_REGISTRY.md#26-round21-tpex_spendi_today-code-only-停牌推論修正有限資料品質修正已-review) 與 [§7.4](SOURCE_REGISTRY.md#74-round21-c021-cd023-c-today-announcement-code-only-final-review-證據)。本批只修正一個已有消費者的 false-positive path；不把 raw 有保存寫成內容已驗，也不把事件日期、caller `end` 或 local capture time 混成 first availability。`success + force=False` 的 zero-call reuse 不修舊旗標；新 fetch 也不自動重算舊 tracking。

### 1.10 Round22／TPEx history `Serial` 身分修正

| 狀態 | 依賴與輸入 | 本批完成條件 | 不在本批 |
| --- | --- | --- | --- |
| `已 review`（有限資料品質修正） | 既有 `parse_tpex_suspension_history_rows`、history raw／Event／tracking consumer；官方 bounded schema `Serial=編號`、`SecuritiesCompanyCode=證券代號`。 | 只移除 `Serial` identity fallback；保留 `SecuritiesCompanyCode → Code → 證券代號 → 代號` local precedence、first-nonblank、exact `allowed_symbols`、raw／event provenance 與日期行為。Serial-only 不產生 Event，Code／中文 alias 不再被 Serial 遮蔽；作者 34 cases／97-pass targeted、統籌 15／15 independent 與 730-pass full 通過。 | 新 alias conflict/type policy、日期倒置／malformed resume／intraday／future schedule 改寫、first availability／revision／PIT、history capture loader、完整停復牌 coverage、舊 Event cleanup／tracking replay、正式 DB 修復或排程。 |

既有成功 request 的 `force=False` 可能 zero-call reuse；`force=True` 只重抓並 upsert 新結果，empty／ignored／另一證券資料不會刪除舊錯 Event。作者 migration-created SQLite／actual both-market Official＋`collect` 證 raw FK、gap／tracking 與 reuse／force 邊界；統籌 15 checks 使用 actual `TpexAdapter` 與真 SQLite，含同 symbol 的 TWSE／TPEx isolation，但不是 whole `collect`、無網路，且以 current `Base.metadata` 建 DB。證據歸屬與 hash 見 [SOURCE_REGISTRY §2.7](SOURCE_REGISTRY.md#27-round22-tpex-history-serial-身分修正有限資料品質修正已-review) 及 [§7.5](SOURCE_REGISTRY.md#75-round22-c022-b-tpex-history-identity-有限-review-證據)。

### 1.11 Round23／TPEx history split-row resume linkage

| 狀態 | 依賴與輸入 | 本批完成條件 | 不在本批 |
| --- | --- | --- | --- |
| `已 review`（有限資料品質修正） | Round22 identity precedence；既有 `_text(...)`／`parse_roc_date(...)`、history raw／Event／tracking consumer；D025-A 保存的 exact 362-row body。 | 對 selected symbol 的全部輸入列計數；只有恰好兩列、一列 start 可解析且 resume raw text 空白、另一列 resume 可解析且 start raw text 空白，並滿足 `start < resume` 才 link。suspension 保留 start `source_row`，既有 `resumed_date`／`interval_end` 由 null 補值，另新增 `resumption_source_row`；resumption Event 不變。作者 45 cases／142-pass targeted、統籌 19／19 independent 與 775-pass full 通過。 | strict date／alias conflict／type／time policy、malformed／倒置／same-day／duplicate／multiple-cycle hardening、gap／future cutoff／schema 改寫、history capture、first availability／revision／PIT、舊 Event cleanup／evaluation replay、完整停復牌 coverage、正式 DB 或排程。 |

D025-A 的 181 unique pairs 由獨立仿寫 predicate 得出；統籌 `live_shape_review` 是不 import production parser 的 offline shape oracle，production parser 的原序／反序／seed 23 打亂則屬 19-check independent review。actual adapter 對 full saved body 的 synthetic universe 只選 `1788` 兩個 Event；這不是 live whole-181 DB consumer。不合格 shape 保留舊 row-local 行為，仍可能有 null end／無界 tracking。`force=False` 可 zero-call reuse；`force=True` 可更新同 key details；raw content 可 dedupe，舊錯 Event 與既存 evaluation 不自動修。證據歸屬、hash、HTTP request count 與 guard 見 [SOURCE_REGISTRY §2.8](SOURCE_REGISTRY.md#28-round23-tpex-history-split-row-resume-linkage有限資料品質修正已-review) 及 [§7.6](SOURCE_REGISTRY.md#76-round23-c023-bd025-b-split-row-linkage-final-review-證據)。

### 1.12 Round24／TPEx 公司行動 ratio／reference mapping

| 狀態 | 依賴與輸入 | 本批完成條件 | 不在本批 |
| --- | --- | --- | --- |
| `已 review`（有限資料品質修正） | 既有 `TpexAdapter.fetch_actions`、`CorporateAction` 與 `_corporate_action_factor`；官方 TPEx daily Swagger／公式頁；D026-A 保存的三筆 cash-only body；official-schema-shaped synthetic ratio rows。 | `stock_dividend_ratio` 只讀 `StockDivdendThousandShares`／local `每仟股無償配股`，parsed non-null 後 `/1000`；`reference_price` 只讀 `ClosePriceBeforeExRightsDiviend`／local `除權息前收盤價`。貨幣 `StockDividend/權值` 與 post-action `OpeningReferencePrice/開始交易基準價` 不再落入兩 slot。作者 dedicated 34／targeted 79 passed；統籌 26／26 independent、完整 backend 809 passed／1 skipped及 109 TOTAL guard 通過。 | paid-subscription、`ExRightsDiviendQuote/P` explicit factor、`tpex_exright_prepost` join、TWSE、cash precision、numeric 全面 hardening、schema／version、capture／registry／PIT、舊 action／evaluation 自動 repair／replay、正式 DB／排程。 |

三筆保存 daily rows 都是 ROC 1150914 cash-only；2026-09-13 as-of 的 actual adapter 應得零，2026-09-14 replay 是隔離 future-as-of exercise，不是 historical availability。non-zero TPEx ratio 是 schema synthetic，不是 live row。只在本輪具名正常輸入（finite `P>C≥0`、`Rf≥0`，且無 paid 或其他同日調整）中，既有 factor 才與官方 `(P-C)/(P×(1+Rf))` 等價；missing pre-close 繼續走 prior-bar fallback，但不是 Article 57 truth。完整契約、7 次 direct GET、來源／consumer 證據歸屬與限制見 [SOURCE_REGISTRY §2.9](SOURCE_REGISTRY.md#29-round24-tpex-公司行動-ratioreference-mapping有限資料品質修正已-review) 與 [§7.7](SOURCE_REGISTRY.md#77-round24-c024-bd026-b-公司行動-mapping-final-review-證據)。

### 1.13 Round25／TPEx 公司行動 cash precision

| 狀態 | 依賴與輸入 | 本批完成條件 | 不在本批 |
| --- | --- | --- | --- |
| `已 review`（有限資料品質修正） | R24 ratio/reference mapping；R24 frozen official Swagger／daily／prepost／公式頁；既有 `_text`、`parse_number`、identity／upsert 與兩個 factor consumers。 | `cash_dividend` first-nonblank 僅改為 `CashDivdend` → `CashDividend` → `現金股利` → `息值`；blank 才 fallback、nonblank invalid 不降級、single existing parse。5278 得 0.26618165／Fraction factor `472676367/478000000`，6204／8423 不變；相同 action ID、raw bytes／FK、future cutoff 與兩 consumer 通過。 | paid／TWSE type-reference、quote/tick rounding、numeric 全面 hardening、schema／execution version、capture／registry／PIT、舊 action／evaluation 自動 repair／replay、正式 DB／排程。 |

R25 沒有新增網路；沿用的 daily request observation 是 R24 2026-09-13 07:01:09 +08:00，receipt 另於 23:04:24 UTC 產生。作者 final 101 passed；統籌 independent 29／29、完整 backend 831 passed／1 skipped、110 TOTAL guard unchanged，均 exit 0。主 29-check 的 SQLite path 是 direct `_upsert_action(raw FK=None)`；whole-collect／raw-FK／reuse-force 歸作者 integration。existing fallback 是 `MarketBar.close`，不保證 official/Article 57 truth。Paid 仍需可信 `Rp/S/P`、持久化與版本策略，schema/migration 只是可能方案；TWSE type-only 另有 double-action／double-factor 風險。完整契約見 [SOURCE_REGISTRY §2.10](SOURCE_REGISTRY.md#210-round25-tpex-公司行動-cash-precision有限資料品質修正已-review) 與 [§7.8](SOURCE_REGISTRY.md#78-round25-c025-bd027-b-cash-precision-final-review-證據)。

### 1.14 Round26／TWSE action source classification

| 狀態 | 依賴與輸入 | 本批完成條件 | 不在本批 |
| --- | --- | --- | --- |
| `已 review`（有限唯讀投影） | 既有 instrument detail／CorporateAction；D028-A 保存的 TWSE body／Swagger；exact `Code`／`Date`／`Exdividend` 與 local identity。 | `corporate_actions[]` additive `source_action_classification`；exact source/exchange/fields、ASCII ROC date、identity、aliases、三個 enum 與固定 reason precedence fail closed。既有 `type`／identity／rows 不變；作者 targeted 149 passed，統籌 independent 129、full backend 935 passed＋1 skipped，old/new 19 queries。 | source admission／capture、raw-body membership、official event ID／authenticity、reference／paid factor、worker／factor／schema／frontend、舊 action dedupe／evaluation replay、historical availability／revision／PIT、正式 DB repair／排程。 |

C026-B external `saved.py` 對 68-row 保存 body 的 actual adapter＋helper 在 2026-09-13 cutoff 輸出 6 rows，2026-12-31 才輸出全 68；這不是 whole `collect`，也不是 PIT。C026-B whole-collect 另用 synthetic 2026-09-04 單一 `息` row 驗 reuse／force、raw identity、兩 consumer factor `0.99875` 與舊 evaluation retained；D028-A 是無 production import 的 standard-library 26-case oracle。完整契約、reason／alias 邊界與證據歸屬見 [SOURCE_REGISTRY §2.11](SOURCE_REGISTRY.md#211-round26-twse-source_action_classification有限唯讀投影已-review) 及 [§7.9](SOURCE_REGISTRY.md#79-round26-c026-bd028-b-twse-source-classification-final-review-證據)。

## 2. 目前可接受的已 review 證據

| 批次 | 狀態 | 已 review 證據 | 尚不能宣稱 |
| --- | --- | --- | --- |
| R0-C01／B1 | 已 review（最小相容範圍） | 2026-09-11 統籌：隔離 backend 完整 pytest 128 passed、exit 0；新 rule-only `confidence=null`，legacy 0.75 僅在嚴格 allowlist 下標為非機率語意。詳見 [R0 §5.2](R0_IMPLEMENTATION.md#52-c-001-實際相容行為與驗證)。 | B2 雙版本 artifact、歷史 replay、正式 DB 寫回、完整前端回歸。 |
| R0-C02／B3 第一段 | 已 review（純核心） | 2026-09-12 統籌：ATR targeted 28 passed、exit 0；獨立手算 seed／Wilder、future action fail-closed、前收 precedence；`presentation.test.ts` 獨立編譯與執行 exit 0。final hash 見 [R0 §4.6](R0_IMPLEMENTATION.md#46-c-002-final-review-證據與未完成邊界)。 | 官方 session／公司行動 truth、worker 接線、versioned persistence、paired replay、策略切換、完整 suites。 |
| 歷史 P0／來源驗收 | 歷史紀錄，不是目前整體完成 | 2026-09-10 正式 DB 紀錄：65 個 verified TAIEX sessions；市場窗口達標但 global status=partial，events 65 session unsupported。詳見 [DATA_SOURCES](DATA_SOURCES.md#正式-datastockdb歷史-p0-結果)。 | 今日 coverage、事件為零、全市場／全欄完整、模型或策略有效。 |
| R0-C03／B6 | 已 review（現況查驗與隔離升級） | 2026-09-12 統籌：正式 DB `mode=ro`／`query_only` 前後 hash、mtime、size 不變；當時無 `alembic_version`、有五筆 fallback markers。consistent copy／fresh DB 真 Alembic 升到 0005；副本 20 個既有表（含 fallback marker 表）、622,399 rows 與完整內容 fingerprints 保留；API health 200。有 Alembic 的完整 backend 157 passed、exit 0。詳見 [R0 §8.2](R0_IMPLEMENTATION.md#82-c-003-final-review-證據與限制)。 | C003 沒有升級正式 DB，當時不能稱 Alembic 0005；forward-only restore 未實跑；bundled `.deps` 缺 Alembic。R26 外部 preview 變化不回寫此歷史驗收。 |
| R0-C04／B3-persist 第一段 | 已 review（有限儲存段落） | 2026-09-12 統籌：final `artifact_store.py`／test hash 為 `40CEC8F…`／`B519CF4F…`；ATR＋store targeted 47 passed、完整 backend 176 passed／4486 warnings／26.84 秒、exit 0。獨立 SQLite fixture 驗 ownership、immutable SQL、UTC retry、collision rollback、雙連線冪等；final 補驗缺 null reason 與負 TR／ATR 拒絕、合法 ATR=5 保存。八個 legacy 程式／DB 基線不變。詳見 [R0 §4.8](R0_IMPLEMENTATION.md#48-c-004-final-review-證據與未完成邊界)。 | 此列記錄 Round 04 當時狀態：只驗 caller-supplied metadata 的 immutable store，當時仍待 legacy＋v2＋兩 as-of 比較與完整 provenance；缺口已由下一列 C-006 補足。官方 truth、PIT gate、worker/API 仍分屬 B3-wire／B5-time。 |
| R0-C06／B3-persist 結案段落 | 已 review（有限 storage/provenance/compare） | 2026-09-12 統籌：`atr-provenance/v2` strict contract、schema 1 compatibility、離線雙 read-only compare；完整 backend 200 passed／4592 warnings／25.72 秒、exit 0。final fixture 驗四表 rollback、C-004 bytes/seal 保留、同日兩 as-of 與 pair-specific comparable/incomparable；11 個保護檔不變。詳見 [R0 §4.9](R0_IMPLEMENTATION.md#49-c-006-provenancecompatibility-final-review-與完成邊界)。 | B3-persist 只按 caller-provided 結構、隔離保存與離線比較結案；不證官方 truth、PIT execution gate、worker/API、正式 DB、B7 或整體 R0。legacy provenance 固定 caller-declared-only／不可與新 artifact 宣稱可比。 |
| R0-C07／B5a local foundation | 已 review（有限本地核心／儲存） | 2026-09-12 統籌：`time-evidence/v1` 純 contract、專用 schema 1 store、exact reader／lineage history 與 JSON export 通過；完整 backend 215 passed／4592 warnings／24.03 秒、exit 0，作者 final targeted 15 passed／0.32 秒。專案外 `review.json` 的 22 項獨立檢查全過，`protected-review.json` 的 15 個既有程式／DB 目標 hash、size、mtime 全不變；四個 source hash 見 [R0 §7.1](R0_IMPLEMENTATION.md#71-round07-c007b5a-final-review有限本地-foundation)。 | 只證明 caller-provided 時間角色、UTC/date-only/unknown、revision/supersedes、append-only transaction、exact selector、legacy-safe 與 atomic no-clobber export。本批未改 News/API/worker/UI、未跑 frontend、未驗官方 truth 或 B5b PIT；B5a 產品輸出接線、B2、B3-wire、B7 與 R0 仍未完成。 |
| R0-C08／B5a product projection | 已 review（有限 read-time/API/UI） | 2026-09-12 統籌：`product-time/v1` 覆蓋 News、signal、action、stock、dashboard、tracking compact／nested output；完整 backend 221 passed／4603 warnings／24.55 秒、四個 frontend self-test、跨 TZ presentation、TypeScript 與 82-module production build 全過。18 個 API response 排除本次動態 generated 欄位後無 legacy diff、17 個入口 query count 相同、8 組同 subject projection 一致，16 個時間邊界案例與 15 個保護目標通過。詳見 [R0 §7.2](R0_IMPLEMENTATION.md#72-round08-c008b5a-產品-read-time-projection有限-review)。 | 只證明既有資料的 read-time 安全標示與相容性；不接 C007 strict store／worker、不保存新時間、不證官方 availability truth，不執行 B5b PIT、B3-wire、B7 或整體 R0。 |
| R0-C12／B2-persist foundation | 已 review（有限 pure/local store；Round12 歷史） | 2026-09-12 統籌：`signal-artifact/v1` pure normalization、version binding、immutable root／withdrawal revision、attempt/run relation、exact／filtered reader、ownership 與 collision rollback 通過；完整 backend 285 passed／4625 warnings／16.95 秒、exit 0，獨立矩陣 45／45，作者與文件角色 targeted 均為 26 passed。四個 final hash 與欄位對齊見 [R0 §5.5](R0_IMPLEMENTATION.md#55-round12-c012-final-review-證據與未完成邊界)。保護目標須寫 40／41 unchanged：正式 DB 不變；`.local` 唯一例外可歸因另一個前後端服務 task 依使用者另行要求啟動，不是 C012 寫入。 | 以 Round12 當時狀態，沒有 legacy reader／同日 legacy-new comparison；該有限 slice 後由 Round32 下一列補上。完整輸入 replay、API list/detail/action、DecisionSummary、UI、worker、官方 availability／PIT 或 B7 仍未完成；不寫正式 DB、不自動切預設版本，不宣稱 B2 或 R0 完成。 |
| R0-C32／B2 offline exact comparison | 已 review（有限 library） | 2026-09-13 統籌：`signal-comparison/v1` 兩個 external rollback snapshots、required expected SHA、exact legacy／artifact selectors、structured missing、hard schema/data/integrity errors、readonly guards 與 detached deterministic report。統籌 matrix 58 cases／68 connections／915 statements；review 作者 full 2,264 passed／2 skipped／12,414 warnings／exit 0及162 guards；D034 11／11。見 [Signal comparison](SIGNAL_COMPARISON.md)與[R0 §5.6](R0_IMPLEMENTATION.md#56-round32-c032-b-offline-exact-comparison有限-review)。 | 不執行 paired replay、不證 shared inputs／historical linkage／probability／price delta／availability／PIT，不接 CLI／API／UI／worker/default。B2、B7、完整 replay、來源 truth與預設切換未完成；各 run 數字不得相加。 |
| R0-C33／B2 current pure-rule replay | 已 review（有限 library） | 2026-09-13 統籌：`rule-replay-bundle/v1`／report；two-evaluator complete caller arguments、canonical digests、whole-source/config/CPython binding、fresh private execution、strict JSON/limits/errors。作者 targeted 151 passed＝141 new＋10 domain、full 2405 passed／2 skipped／12414 warnings，兩個 run 各有 165 guards unchanged；統籌 82／82＋25／25 matrices 各有 164 guards unchanged；四個 run 均 exit 0。Source hashes與完整契約見 [Rule replay](RULE_REPLAY.md)及[R0 §5.7](R0_IMPLEMENTATION.md#57-round33-c033-b-caller-provided-current-pure-rule-replay有限-review)。 | 不證 caller inputs 的 subject/time/source/availability、historical recovery、authentication、PIT 或完整 Signal；不接 SignalArtifact/store、worker、API/UI、DecisionSummary/default，也沒有 legacy-v2 paired replay。B2、B7與完整 replay仍未完成。 |
| R15／產業分類 current-table diagnostic | 已 review（有限程式／隔離診斷） | 2026-09-13 統籌：完整 backend 372 passed／4625 warnings／22.41 秒、exit 0；current／counterfactual 各 1,974 個 supported 標的唯一 expected membership、35 個 unknown／special 無一般 membership；current 既有 derived rows 保留，paired inputs／history 相同，score rows 41／52、signals 各 4,616；integrity、FK、rerun 與正式／`.local` DB 不變通過。詳見 [產業分類契約 §5](INDUSTRY_CLASSIFICATION.md#5-隔離驗收矩陣有限範圍已-review)。 | 不證 fresh 公司分類、歷史 PIT／有效日、策略有效性或正式資料修復；不授權寫正式 DB、覆寫 legacy derived rows 或解除前端 guard。 |
| R16／ordinary-industry normal collector | 已 review（有限接線） | 2026-09-13 統籌：完整 backend 412 passed／4,902 warnings／pytest 31.67 秒、exit 0；實際 TWSE／TPEx universe parser→本地 official-shaped fixture→完整 collect 的 11 checks 於 final 再次 exit 0，aware timestamp probe 亦通過，涵蓋 observation period、empty set、atomic conflict、receipt/retry、domain isolation、integrity／FK 與正式／`.local` DB 不變。詳見 [產業分類契約 §6](INDUSTRY_CLASSIFICATION.md#6-round16-normal-collector-觀測期間有限接線已-review)。 | 不證 live source、capture metadata／availability truth、source effective date、PIT、既有 naive raw 時間修復、ETF／new-listing 歷史期間或正式資料修復；正常 collect 仍可更新行情收錄時間，不能稱所有表重跑不變。 |
| R17／ETF 與 new-listing candidate lifecycle | 已 review（有限接線） | 2026-09-13 統籌：完整 backend 481 passed／5,066 warnings／pytest 49.91 秒（process 51.328 秒）、exit 0；actual TWSE／TPEx parser→local official-shaped fixtures→完整 collect 11 checks、SQLite savepoint rollback probe、integrity／FK 及驗證期間四個 frozen source／正式與 `.local` DB fingerprints 不變。詳見 [產業分類契約 §7](INDUSTRY_CLASSIFICATION.md#7-round17-etfnew-listing-candidate-lifecycle有限接線已-review)。 | 不證 live source truth、ETF heuristic 品質、legacy／bounded hot 歷史修復、synthetic index lifecycle、PIT、ordinary-industry↔ETF 歷史轉換、正式資料修復、guard 解除或策略有效性；B 版 477 passed 與失敗 probe 不是 final。 |
| R18／source registry standalone capture | 已 review（有限 runtime） | 2026-09-13 統籌：`source_runtime.py`／test hash `4E80D8D…FA927D`／`7164630A…A38C2`；完整 backend 519 passed、1 skipped、5,066 warnings／pytest 57.36 秒（process 58.75 秒）、exit 0；33／33 independent checks 通過，驗證期間納入 guard 的程式／測試來源與兩 DB unchanged。一次真正 `twse_stock_day_all` CLI 為 1 GET／HTTP 200／319,396 bytes／1,379 rows，bundle body／receipt integrity 通過。詳見 [SOURCE_REGISTRY §7.1](SOURCE_REGISTRY.md#71-round18-c018-standalone-source-capture-final-review-證據)。 | 不證另外三筆 live、內容／availability truth、官方 numeric rate limit、跨 process quota、hard total deadline、legacy collector、summary、PIT／strict evidence、正式 DB 或排程；symlink 權限案例 skipped，Windows junction 真實案例通過。 |
| R19／`STOCK_DAY_ALL` content／consumer | 已 review（有限 library opt-in） | 2026-09-13 統籌：完整 backend 590 passed、1 skipped、5,198 warnings／pytest 47.27 秒（process 48.344 秒）、exit 0；code／tests 與兩 DB fingerprints unchanged（docs 不在 guard）。獨立 capture 30／30：保存 bundle 1,379 rows→1,367 個有效 rows、12 個 unavailable；consumer 7／7：真實 adapters／`collect`、HTTP 全禁，結果 partial／2 records／1 TAIEX／10 raw，並驗舊 bar、只有完整 `ingestion_run_id + source + endpoint + sha256` 相同才 raw reuse、session、integrity／FK。volume probe 證 `9007199254740993.0` 精確保存。詳見 [SOURCE_REGISTRY §7.2](SOURCE_REGISTRY.md#72-round19-c019-b-stock_day_all-contentconsumer-final-review-證據)。 | 不證新 live、另三 domain、兩市場完整內容、unused symbols coverage、authenticity、availability／PIT、C007／B5b、summary、正式分類／DB／排程；plain materialization 非雙檔 atomic／永久 immutable，stale bar／`adj_close` fallback 保留。 |
| R20／`holidaySchedule` positive exclusion | 已 review（有限內容／既有 consumer） | 2026-09-13 統籌：三個 frozen file hashes 見 [SOURCE_REGISTRY §7.3](SOURCE_REGISTRY.md#73-round20-c020-b-holidayschedule-contentconsumer-final-review-證據)；完整 backend 678 passed、1 skipped、7,201 warnings／pytest 53.89 秒（process 55.016 秒）、exit 0；final independent 17／17 checks、code／source 與兩 DB guard 通過。保存的 27-row live bundle 得到 24 closed／18 weekday／3 non-closure；隔離 consumer 為 partial、26 records、13 TAIEX、48 raw。 | 不證完整年度／歷史 calendar、open-session coverage、first availability／revision／PIT、ATR strict evidence、公司行動／停復牌、完整 collector、legacy grammar 修復、既有 closed rows 修復或正式 DB 寫入。 |
| R21／`tpex_spendi_today` code-only 修正 | 已 review（有限資料品質修正） | 2026-09-13 統籌：五個 frozen code／test hashes 見 [SOURCE_REGISTRY §7.4](SOURCE_REGISTRY.md#74-round21-c021-cd023-c-today-announcement-code-only-final-review-證據)；作者 targeted 177 passed，完整 backend 696 passed、1 skipped、7,432 warnings／pytest 53.56 秒（process 54.610 秒）、exit 0。independent actual-adapter／真 SQLite 9／9 checks 證正常 bar 不再被 code-only today row 覆成 suspended、tracking trigger／comparable 修正、raw／integrity／FK 與明確外部 suspension flag 保留；106 個 code／tests／兩 DB guard 路徑 unchanged。 | 不證 endpoint live payload／完整 catalog、effective-session／return／signal eligibility 獨立行為、history capture／parser／tracking interval、first availability／revision／PIT、retroactive repair／replay、完整停復牌 coverage、正式 DB 修復或排程。 |
| R22／`tpex_spendi_history` `Serial` 身分修正 | 已 review（有限資料品質修正） | 2026-09-13 統籌：`sources.py`／新 identity test hashes 見 [SOURCE_REGISTRY §7.5](SOURCE_REGISTRY.md#75-round22-c022-b-tpex-history-identity-有限-review-證據)；作者新增 34 cases，targeted 97 passed、1,597 warnings／pytest 4.71 秒。完整 backend 730 passed、1 skipped、8,093 warnings／pytest 55.53 秒（process 56.688 秒）、exit 0；independent actual-adapter／真 SQLite 15／15 checks，107 個 guard paths（含兩 DB）unchanged。 | 不證新 live payload、完整 catalog／history、alias conflict/type validation、日期／intraday／future policy、history capture 接線、first availability／revision／PIT、舊 Event cleanup／tracking replay、完整停復牌 coverage、正式 DB 修復或排程。 |
| R23／`tpex_spendi_history` split-row linkage | 已 review（有限資料品質修正） | 2026-09-13 統籌：`sources.py`／新 interval test hashes 見 [SOURCE_REGISTRY §7.6](SOURCE_REGISTRY.md#76-round23-c023-bd025-b-split-row-linkage-final-review-證據)；作者新增 45 cases，五 module targeted 142 passed、1,846 warnings／pytest 5.24 秒。完整 backend 775 passed、1 skipped、8,342 warnings／pytest 55.09 秒（process 56.281 秒）、exit 0；independent 19／19 checks，108 個 guard paths（106 個 code／tests／frontend 加兩 DB）unchanged。 | 不證 live whole-181 DB consumer、完整 headers／history、其餘 shape hardening、time／session、history capture、first availability／revision／PIT、舊 Event cleanup／evaluation replay、完整停復牌 coverage、正式 DB 修復或排程。 |
| R24／TPEx 公司行動兩欄 mapping | 已 review（有限資料品質修正） | 2026-09-13 統籌：`sources.py` SHA-256 `8381ab59b4ddc462f354ccbab5642f2dd2c84b2b4b3a3cdf8f45a7886c0e0211`、新 test SHA-256 `be1fd88112b560a17408693edc7b7e33ecd82869a9d5ca76ea87db05db2cb9a8`；作者 34-case dedicated、79-pass targeted；完整 backend 809 passed、1 skipped、8,731 warnings／pytest 56.26 秒（process 57.5 秒）、exit 0；independent 26／26 checks，109 TOTAL=107 source/code/tests/frontend＋2 DB guard unchanged。 | 不證 non-zero live daily row、paid subscription、cash precision、numeric 全面 hardening、TWSE、完整公司行動、source admission／capture、historical availability／revision／PIT、舊 action／evaluation 自動 repair／replay、正式 DB 或排程。 |
| R25／TPEx 公司行動 cash precision | 已 review（有限資料品質修正） | 2026-09-13 統籌：`sources.py`／R24 test／新 precision test SHA-256 為 `7f6e91e8…efe9f`／`642af878…90a11`／`c87ecc93…7598`；作者 22-case 新測、final 四模組 101 passed／1,236 warnings；統籌 29／29 independent，完整 backend 831 passed／1 skipped／8,873 warnings、pytest 57.19 秒（process 58.391 秒）、110 TOTAL guard unchanged，均 exit 0。D027 final oracle 14／14。 | 不證官方 displayed quote/tick rounding 完全一致、paid、TWSE type/reference、numeric 全面 hardening、capture／registry／PIT、版本／既有 artifact 重現、舊 action／evaluation 自動 repair／replay、完整公司行動、正式 DB 或排程。 |
| R26／TWSE action source classification | 已 review（有限唯讀投影） | 2026-09-13 統籌：`api.py`／新 test SHA-256 為 `36118fae…b17735`／`529323a0…a2a83`；作者 targeted 149 passed／335 warnings；統籌 independent 129 checks、完整 backend 935 passed／1 skipped／9,024 warnings、old/new 19 queries，均 exit 0。D028-A oracle 26／26。 | 不證 capture／source admission、raw-body membership、official event ID／authenticity、TWSE reference／paid factor、worker／factor／schema／frontend、舊 action repair／dedupe、evaluation replay、availability／revision／PIT、完整公司行動、正式 DB repair 或排程。 |

## 3. 依賴順序與共同 gate

建議小批依賴；來源 registry 契約與免費來源可行性可和 B6／B2／B3 schema 工作並行，只有實際資料接線才等待對應的時間與 artifact 邊界：

```text
G-SOURCE registry／免費來源可行性 ───────────────┐
                                                ├─> 各來源接線與 R1 對應批次
B6 安全基線 ─> B2/B3 可並存 artifact 儲存 ──────┤
        ├─> B4 規則參考價與新 trade-plan 版本    │
        └─> B5 point-in-time 時間與 as-of gate ──┘
                    └─> B7 同 snapshot paired replay／統籌 review

已准入且實際需要的 R1 來源 ─> 對應 R2 功能 ─> R3 預先登錄驗證／前瞻模擬／採用 gate
```

| Gate | 必須先決定／證明 | 未通過時的行為 |
| --- | --- | --- |
| G-SAFE | 指定 DB 路徑、唯讀正式庫、外部隔離副本、可恢復備份、完整性與 row preservation。 | 不執行 migration、重算或 replay。 |
| G-ID | feature／strategy／execution／prediction／signal-output semantics／presentation 版本與 artifact identity。 | 不得原地覆寫 legacy 列或沿用同版本名改語意。 |
| G-TIME | market、published、first available、collected、revision、decision、generated、earliest execution 的角色及 timezone。 | 歷史 replay 排除該輸入；live run fail-closed。 |
| G-SOURCE | 來源所有者、官方／媒體類型、免費條件、保存／摘要權利、延遲、修訂、歷史範圍與停用方式；`local_fetch`／`raw_store`／`summarize`／`historical_pit` 分開決策。 | 只有缺證據的該用途回 `restricted`／`unsupported`；保留 `unknown + reason`，不可把 unknown 改寫成明文禁止，也不可讓一個用途自動准入其他用途。 |
| G-PRODUCT | 產品設計可先使用 ROADMAP 的盤後 long、數天至數週假設；精確持有期、是否做空與一般研究風險口徑可由統籌另立版本化方案。只有產生個人化部位時才需要使用者的個人風險預算。 | 個人風險 ratio 未知時保持 null、不給具體張數；不宣稱 T+5／T+20 是退出日。 |
| G-MODEL | 預測事件、H、成本、不可比規則、資料切分、校準與採用門檻由統籌在看測試結果前預先登錄並版本化；只有涉及個人偏好／風險的參數才另詢問使用者。 | 未預先登錄時模型只作探索；`probability=null`，不可採用。 |
| G-FORWARD | 每日 plan 先封存，再等觸發與 H／退出規則走完；累積事先規定的有效樣本與市場狀態。 | 狀態維持 `等待`，不能用歷史 fixture 或短樣本提前結案。 |

## 4. R0：修正研究基準與時間口徑

### R0-A：安全與 migration 基線

| ID | 狀態 | 小批與依賴 | 可驗收完成條件 |
| --- | --- | --- | --- |
| R0-A1／B6 | 已 review（有限範圍；Round10 補 synthetic restore mechanics） | G-SAFE；migration graph、正式 DB 唯讀現況、外部 Temp consistent backup、upgrade、fresh DB。 | Round03 已符合 [R0 §8.1](R0_IMPLEMENTATION.md#81-b6-review-驗收矩陣) 除實際 restore drill 外的本批要求；正式 DB 不變，副本與 fresh DB 到單一程式 head，integrity／FK 通過。Round10 另對六表 synthetic slice 實跑 consistent backup→故障副本→新 Temp path restore，但這不回寫 Round03 歷史，也不是正式 restore／deployment drill。 |
| R0-A2 | 已 review（僅 News JSON defaults parity／atomic migration regression 明列範圍） | R0-A1；C010 regression／restore mechanics；C011 `0006_news_json_defaults` 與 SQLite repair helper。 | C010 的固定 synthetic 0004 pre-head fixture、真正 Alembic upgrade、五個 0005 target columns、完整 slice fingerprints、constraints／indexes、integrity、冪等、fresh comparison 與 restore fault detection 保留。C011 已補齊 `symbols_json`／`theme_ids_json` SQL `[]` defaults，並驗 fresh、old005-like fixed slice、explicit 0004→0005→0006、Alembic／fallback、FK 0／1及安全重跑；主 24／24 atomic fault 矩陣涵蓋 Alembic engine、Alembic external Connection、fallback 的 fresh／old005，不把 0004 說成也跑完全部故障交叉。統籌另以 genuine old full 005 Temp copy 完成獨立驗證。此狀態不等於所有 historical schema parity、未支援 custom schema、非 SQLite、正式 DB upgrade、正式 restore／deployment 或 R0 完成；完整證據見 [R0 §8.4](R0_IMPLEMENTATION.md#84-round11-c011json-server-default-parity-與-atomic-migration-回歸有限-review)。 |
| R0-A3／R27 | 已 review（有限 API startup readiness） | R0-A1／A2；C027-A 歷史調查；D029-A 決策契約；C027-B `database_readiness`。 | lifespan 只讀檢查唯一 current Alembic head 或合法 fallback family、必要 mapped schema identity 及兩個 News defaults；缺檔／版本／結構錯誤 fail closed，schema mutation 只由明確 `init-db`／worker 執行。39-case independent startup review、1,011-pass full backend、具名 20-table／622,399-row preservation 與 21-table replay parity 通過。readiness 本身不執行完整 integrity／row／data-FK scan；正式 migration／restore／deployment、所有 custom schema、非 SQLite、資料 truth／PIT 或 running service reload 不由本批接受；完整邊界見 [R0 §8.6](R0_IMPLEMENTATION.md#86-round27-api-startup-readiness有限-review)。 |
| R0-A4／R28 | 已 review（僅 canonical legacy instruments identity rebuild 的有限 SQLite 範圍） | R0-A1；現行0001→0006 chain；R28 Phase A defect evidence；finite state／allowlist contract。 | Alembic Engine、inactive external Connection與fallback三入口；FK0／1；canonical legacy成功、recognized current有限identity no-rebuild、九個具名application inbound FK保存。inbound只支援simple `instrument_id→id`、`NO ACTION`／`NO ACTION`／`MATCH NONE`且non-deferrable；mixed／neither／partial／expression／reversed identity、duplicate、unsupported custom legacy schema、TEMP／scratch與已知0002–0006 marker搭配absent／legacy parent均fail closed。frozen `206+16=222` independent cases驗96個fault exact rollback／same-DB retry；final full backend `1,397 passed／1 skipped／12,029 warnings`、exit0，386個新cases全走過。custom自動保存、任意historical schema、non-SQLite、salvage、正式migration／restore／deployment、資料truth／PIT不在本批。 |
| R0-A5／R29 | 已 review（僅 canonical legacy `signal_settlements` identity rebuild 的有限 SQLite 範圍） | R0-A1；現行0001→0006 chain；R29 Phase A defect evidence；D031-A修正後finite contract；R28 transaction envelope。 | Alembic Engine、inactive external Connection與fallback三入口；FK0／1；unmarked exact known9／known14 signal-only legacy成功，missing／NULL horizon刻意normalize 20，其他known typed payload／id保留；recognized current有限essential-semantics no-rebuild。legacy inbound、unsupported custom schema、noncanonical outbound、mixed／neither／partial／expression／reversed identity、scratch／TEMP與known0001–0006 marker搭配absent／legacy settlement均fail closed。frozen `408+14=422` independent cases驗統籌主矩陣84 faults exact rollback／same-DB retry；final full backend `1,837 passed／1 skipped／12,414 warnings`、exit0，158 guards unchanged。API readiness mixed-identity補強、arbitrary current CHECK／trigger／secondary nonunique index audit、non-SQLite、salvage、正式migration／restore／deployment與資料truth／PIT不在本批。 |
| R0-A6／R30 | 已 review（僅 API startup settlement UNIQUE metadata gate） | R0-A3；R0-A5留下的external mixed-identity候選；D032-A finite metadata contract。 | 至少一個ordered full ordinary BINARY ASC `UNIQUE(signal_id,horizon)`；所有key parts觸及target的UNIQUE必須同形，expression UNIQUE保守拒絕。重複canonical、unrelated named-column UNIQUE與nonunique extras可存在；identity分類只看keyparts、不解析partial predicate，任意CHECK／trigger／unrelated UNIQUE不audit，ASC／reverse是policy，pass不保證任意INSERT。87 populated DB／261 entries＋261 memory probes、final full `1,963 passed／1 skipped／12,414 warnings`、159 guards unchanged已驗；不做row scan、DDL、migration或repair，non-SQLite、正式deployment、資料truth／PIT與instruments mixed候選不在本批。 |
| R0-A7／R31 | 已 review（僅 API startup instruments UNIQUE metadata gate） | R0-A3／A4；R30留下的external instruments mixed-identity候選；D033-A finite contract。 | `market`只列target compatibility、不升格identity；mapped `market`／`exchange`／`symbol`須`hidden=0`，至少一個ordered full BINARY ASC `UNIQUE(exchange,symbol)`，其餘target-key UNIQUE須同形，任意UNIQUE expression拒絕。key-unrelated named UNIQUE可含generated extra／partial／collation／DESC，不解析predicate/dependency且不保證任意INSERT；strict startup可比R28 current no-rebuild更窄。123 populated DB／369 entries＋492 memory probes、final full `2,161 passed／1 skipped／12,414 warnings`、160 guards unchanged已驗；不做row scan、DDL、migration或repair，正式deployment、non-SQLite、custom schema、資料truth／PIT不在本批。 |

R0-A7不回寫R28：explicit migration的recognized-current只作有限no-rebuild判定，startup可拒絕它未稽核的額外shape；`worker.cli init-db`也不承諾移除這些custom constraints。R31 synthetic seeds及backend migration tests確有執行，但正式／`.local` DB只受fingerprint guard且未被SQLite-open；目前checkout未重啟service，輪末I070索引仍待source／docs freeze後驗證。R31 交出的 opt-in offline signal comparison 候選已由 Round32 依上列有限 library 範圍接受；這不是 R31 新增實作，也不表示B2、B7、PIT、來源truth或default切換完成。

R0-A4不反向修改R0-A2：Round11 News helper的支援／拒絕形狀與歷史24／24、73／73仍按當時證據。R28只把 `test_news_json_defaults.py::_old_005_engine` 原本 neither-identity 的 instruments prerequisite改成完整current `(exchange,symbol)` identity，保留`id=1`／`symbol=2330`；只有兩個SQL fixture expressions變動，其餘AST、News schema／rows／self-FK／defaults／trigger／index／fault assertions都不變。R0-A4也不由R0-C5／B7阻塞，但不使R0完成；B3-wire、B5b、B7等產品研究依賴仍保留。

驗收來源為C028-B六檔freeze manifest `3edb72132099cc746ea0309de1e9bbea62bf78f056ae0db123fd0906e877c0b5`。作者run04 `464 passed`在最後marker patch前；final run05只跑selected subset `249 passed／1,191 warnings／51.38s／exit0`，沒有作者final full。統籌final full為`1,397 passed／1 skipped／12,029 warnings`、pytest163.09秒／process166.047秒／exit0；本次輸出沒有列skip reason。156 protected paths unchanged，正式與`.local` DB維持R27 fingerprints；round-end codebase index由I067在source／docs freeze後另行刷新，index只能作readback／coverage證據，不能替代上述功能驗收。

R0-A5 不反向修改 R0-A2：News old005 只新增 minimal empty `signals` 及 canonical settlements prerequisite；recovery loader 在 immutable Round10 SQL 之後追加相同兩個 empty `CREATE`，第三個 direct-slice setup 改走 loader。AST 與 hash 核對確認 original assertions、既有 fault payload 與 fixed SQL／JSON bytes 不變。R29 也不修改 R27 readiness：統籌只在保存的 external mixed-identity synthetic DB 重現 `check_database_readiness()` 回 `None`，memory copy 第二個 horizon insert 仍撞 `UNIQUE(signal_id)`；來源未變，這是 R30 候選而非 R29 migration defect 或正式 DB 證據。

驗收來源為 C029-B 七檔 source freeze 及 artifact manifest `1fad7cc5d1874050d50f8658a8c35bc02b954a51bce7e6afaecc8b863526acbf`。作者 targeted 依序為 `407 pass／1 fail`、`428 pass`、`462 pass`；targeted03 的 final 440 new tests 含 96 fault 與 144 false-marker cases。作者 full01 因 launcher 未向 child 傳 `PYTHONPATH` 而 `1,836 pass／1 fail／1 skip`，後續 source-runtime targeted 為 `38 pass／1 skip`。統籌 matrix-01 因自身無 column-list INSERT harness 錯誤 exit 1，修正後 matrix-02 `408／408` 與 special `14／14` 均 exit 0；final full `1,837 passed／1 skipped／12,414 warnings`、pytest 185.52 秒／wrapper 188.562 秒／exit 0，skip 為 Windows symlink privilege unavailable，158 protected paths unchanged。正式與 `.local` DB 未由本批 migration、repair 或 restore；round-end codebase index由 I068 在 source／docs freeze 後刷新。

R0-A6 不回寫 R29：上段 external mixed-identity 是 R29 保存的候選，C030-B 才修改 readiness。production scope只有 `backend/app/database_readiness.py`（SHA-256 `6082c987550d2b9254b4ddde7f3f48fcf1895dd0db531de675a4cb61d6ef8b09`），另新增 `backend/tests/test_startup_settlement_identity.py`（SHA-256 `4e7c0d96e15e0458861fcf2b583d93577dd9e2d93d1bb18a697161ffad72d840`）；既有production AST除helper與單一conditional call外不變。作者final targeted `664 passed／474 warnings`、pytest58.46秒／wrapper59.673秒／exit0，80 guards unchanged；126個新增tests為40 shapes×3 marker families共120 cases，每案內再走direct／repeat／actual lifespan，加6個memory semantics，不與R29 case數混算。memory semantics另固定canonical／mixed、reverse／DESC policy與unrelated UNIQUE／trigger可能阻擋寫入但仍可通過的界線。

統籌final matrix以87個populated external DB走261 entries及261 memory INSERT probes，mismatches `[]`、exit0；`mode=ro`、`query_only`、single `BEGIN`、readonly trace／authorizer no business-row read均通過，且`migrations.upgrade_database`、`_fallback_upgrade`、`Base.metadata.create_all`及settlement preflight／rebuild bombs未觸發，87 DB與protected guards unchanged。final full為`1,963 passed／1 skipped／12,414 warnings`、pytest226.12秒／process229.344秒／exit0；唯一skip是`backend/tests/test_source_runtime.py:238: symlink privilege unavailable`，159 guards的SHA／size／exactmtime不變。正式DB只受既有fingerprint guard且未開啟；本批沒有migration／repair／restore、service、install、Git mutation、deployment、帳戶或交易動作。non-SQLite、attached schema、crash／disk-full／concurrency、任意historical／custom schema、資料truth／PIT仍未驗；下一候選只保留單一external instruments mixed-identity probe，不擴成本輪或宣稱ROADMAP完成。

### R0-B：版本化 artifact 與正確 ATR

| ID | 狀態 | 小批與依賴 | 可驗收完成條件 |
| --- | --- | --- | --- |
| R0-B1／C-001 | 已 review（局部） | 無 migration；confidence 顯示安全化。 | 只維持 §2 已接受證據，不回推 B2 完成。 |
| R0-B2／B2-persist | 已 review（C012 local foundation＋C032-B offline exact comparison＋C033-B current pure-rule replay）；B2 整體未完成 | R0-A1、G-ID；pure/store 見 [Signal artifact](SIGNAL_ARTIFACTS.md)，comparison 見 [Signal comparison](SIGNAL_COMPARISON.md)，current rule bundle 見 [Rule replay](RULE_REPLAY.md)。 | 已通過新 rule-only confidence null、canonical semantics、version binding／immutable store、exact legacy/artifact reader、readonly descriptive comparison，以及 whole-source/config/runtime-bound caller current-rule replay。原完成條件完整保留：可證 subject/time/source/availability 的保存輸入須接 artifact/worker並做隔離 legacy／v2 paired replay；API list/detail/action、DecisionSummary、UI 與 B7 均須明確選版；legacy row/hash不變，不得以同列 marker、comparison subject equality、`arguments_digest`或current `exact_match`冒充 shared historical input／完整 Signal。 |
| R0-B3／C-002 | 已 review（純核心） | 純函式，未接 I/O。 | 只維持 §2 已接受證據。 |
| R0-B4／B3-persist | 已 review（C-004＋C-006 有限 persistence） | R0-A1 的安全原則、G-ID、R0-B3；C-004 的 schema 1 immutable store 見 [R0 §4.8](R0_IMPLEMENTATION.md#48-c-004-final-review-證據與未完成邊界)，C-006 strict provenance、compatibility 與唯讀 compare 見 [R0 §4.9](R0_IMPLEMENTATION.md#49-c-006-provenancecompatibility-final-review-與完成邊界)。 | schema 1 舊 payload/key/seal 原樣保留；`atr-provenance/v2` strict writer/reader 驗完整 caller-provided snapshot、ordered rows、instrument mapping、method/config/implementation、basis、calendar/session/halt、previous-close selected refs 與 action manifest/digest/coverage/source/aware availability。缺漏拒絕，unknown/unavailable 只能配 reason 完整的 fail-closed null。離線 compare 以 legacy stable checkpoint 與 artifact exact key 或完整 version/snapshot/as-of 選取，無 implicit latest，ambiguity 拒絕；legacy-vs-new 固定不可比，v2 pair 的 basis/snapshot/settings/dependency/implementation 不同則 pair-specific incomparable、delta=null。這個完成狀態不含官方 truth、PIT gate、B3-wire worker/API、正式 DB 或 B7。 |
| R0-B5／B3-wire | 提案 | R0-B4、G-TIME、G-SOURCE。 | 官方交易 session、停復牌、公司行動與 previous close adapter 各有 raw／版本／availability 證據；來源不完整時 reason code fail-closed；worker 需顯式 opt-in 才讀新 artifact，預設不切換候選。 |

### R0-C：價位、時間與 paired replay

| ID | 狀態 | 小批與依賴 | 可驗收完成條件 |
| --- | --- | --- | --- |
| R0-C1／B4a | 已 review（read-time semantics） | G-ID；不改 v1 算式、worker、schema 或 legacy 列。完整契約與證據見 [R0 §6.1](R0_IMPLEMENTATION.md#61-legacy-價位的強制標示)。 | nested `signal-level-semantics/v1` 已覆蓋 signal full/compact/list/detail、action list/detail、stock detail、tracking 與 action/stock UI。只有 `breakout_v1@1.0.0`、`pullback_v1@1.0.0` 可宣告 `legacy-risk-levels/v1`；unknown identity fail-closed。basis／historical generated/decision time 無證據時為 null+machine reason，`response_generated_at` 另列；持倉成本／stop 與 tracking fill 不冒充規則參考價。統籌 full backend、四前端 test、build、N+1 與外部 fixture UI 查驗通過；signals/tracking UI 為 redirect。 |
| R0-C2／B4b | 提案 | R0-C1、G-PRODUCT；新 trade-plan／execution version。 | tick-size 後仍 `invalid < entry < target_1 < target_2`；gap、成本不足、流動性不足、停牌與日線無順序均拒絕或 incomparable；legacy 1.6R／3R 可重現且不被覆寫。 |
| R0-C3／B5a | 已 review（有限 local foundation＋product read-time projection） | R0-A1、G-TIME；C007 `time-evidence/v1` caller-provided 純契約與明確 opt-in 專用 store；C008 `product-time/v1` 是分離的既有 API/UI read-time projection。 | C007 的 strict role／revision／exact store 行為與 C008 的 News、signal、action、stock、dashboard、tracking 角色顯示、legacy 相容、compact/nested consistency 已分別 review。兩者尚未有 persisted linkage；官方 truth 與 B5b PIT 另做，不能把 read-time unknown 標示當成 execution gate。 |
| R0-C4／B5b | 提案 | R0-C3；as-of reader／writer gate。 | 每個必要版本 `available_at <= decision_at`，live 另要求 `collected_at <= decision_at`；T+2 修訂不改 T+1 artifact；無可信 first_available_at 的 backfill 不進歷史決策。 |
| R0-C5／B7 | 提案 | R0-B2、R0-B5、R0-C2、R0-C4。 | 同一唯讀 snapshot 產生隔離 legacy／new output；差異報告涵蓋 ATR、狀態、confidence、價位、availability、migration 與所有不可比；統籌重現成功、缺資料、gap、公司行動、legacy confidence、盤後可得與修訂案例。 |
| R0-C6 | 等待 | R0-C5 統籌 review。 | R0-1～R0-4 只按各自已 review 範圍更新；研究結果與預設版本切換須有 B7 證據並另做決策。R0-5 可在 B6 獨立 review 後更新，不必被 B7 反向阻塞。純核心、schema 存在或 fixture 都不足以將整個 R0 標完成。 |

## 5. R1：可靠資料與事件研究

| ID | 狀態 | 小批與依賴 | 可驗收完成條件 |
| --- | --- | --- | --- |
| R1-A1 | 已 review（Round09 foundation＋Round18 capture＋Round19／20 兩個有限 consumer＋Round21–26 六個有限資料品質／投影修正；整體未完成） | G-SOURCE；source registry 契約與免費來源可行性可並行進行，不等待 R0-C4。實際 as-of 接線才依賴 R0-C4；目前只含四個既有官方 GET endpoint，capture consumer 仍只接單日 `STOCK_DAY_ALL` selected-security 與單年度 holiday positive exclusion。 | Round09 已驗版本化唯讀 registry、external pins、用途別 fail-closed decision、最低 evidence／conditions 與四來源人工查證；Round18 補四筆 standalone `local_fetch + raw_store` executor；Round19／20 分別補保存 bundle 的 selected-security 與 holiday request-exclusion opt-in；Round21／22／23 修 today false-positive、history identity／linkage，Round24／25 修既有 TPEx action adapter 的 ratio/reference 與 cash precision，Round26 只為既有 TWSE details 增加 read-only source classification。原完成條件仍保留：其他來源、paid／TWSE reference／raw membership／完整公司行動、完整停復牌、完整 legacy collector、其餘內容與時間 strict evidence、summary、PIT、完整延遲／rate limit／歷史／修訂／停用證據。 |
| R1-A2 | 提案 | R1-A1；官方行情／TAIEX／法人／融資逐域驗證。 | 以 exchange＋symbol＋session＋欄位用途產 coverage；錯日／缺日／unknown 不補 0；TWSE／TPEx 單位與 market identity 不混用；raw 可追溯。 |
| R1-A3 | 提案 | R1-A1、R0-B5；公司行動與停復牌。 | raw／adjusted basis、因子、版本、可得時間與 applied-through 可重建；TWSE／TPEx 覆蓋分開；不足時 ATR／tracking fail-closed。 |
| R1-B1 | 提案 | R1-A1、R0-C4；官方事件與 NewsItem 時間回歸。 | unknown time、date conflict、backfill、revision／withdrawal、feed-only URL、無內文均有案例；排序與 cursor 綁 snapshot／version；無可信時間者不搶占「最新」。 |
| R1-B2 | 提案 | R1-B1；同事件 grouping 與 new-information。 | 同源與跨源 dedupe 可重跑，保留每篇來源；首次／補充／更正／撤回分開；負面或轉載不增加正向催化；所有摘要回指合法原文。 |
| R1-B3 | 提案／可能受限 | R1-A1、G-SOURCE；免費官方 macro／可信媒體可行性。 | 每個候選以實際抓取、時間、保存／摘要權利與穩定性驗證；沒有可接受來源就記 `受限`，不以搜尋摘要或模型記憶補內文。 |
| R1-C1 | 提案（ordinary industry 有 R16、candidate lifecycle 有 R17 有限接線） | R1-B2；官方產業與市場題材分層。Round18 已完成 standalone capture，Round19／20 只接兩個有限 source consumer；正式分類修復仍依自身資料與驗收依賴決定，不以這兩個小批為新增前置。 | membership 保存來源、方法、相關程度、生效／失效與版本；一股多題材；未核實模型關聯不進已確認分類。R16／R17 只證 current observation transitions；未分類 bundle 內 unused symbols 與 holiday request exclusion 都不結清整體題材層、legacy 修復或歷史 PIT。 |
| R1-C2 | 提案 | R1-C1、R1-A2；題材品質與去重。 | 相同 as-of 的相對強弱、廣度、集中度、延伸與事件方向各自有窗口／缺項；重疊題材不重複計候選或曝險；不改 `hot_group_v1` gate。 |
| R1-D1 | 提案 | R1-A1；官方當沖資料。 | 先固定分子／分母、股數／金額、T／T+1／T+2 修訂與 availability；兩市場分開驗證；修訂可按當時版本重放。 |
| R1-D2 | 提案 | R1-A1；融券／借券／持股欄位。 | 每欄來源、單位、日期、revision、coverage 與 null policy 有證據；欄位存在不算已收集。 |
| R1-D3 | 提案／可能受限 | R1-A1、G-SOURCE；券商／分點歷史可行性 gate。 | 免費合法來源須有穩定歷史、通道識別、單位與 point-in-time；不足即標 `受限` 並停在介面，不產生「主力／隔日沖身分」或預測。 |
| R1-E1 | 提案 | R1-A1、R0-C4；必要基本面。 | 只補公司品質／事件驗證所需欄位；會計期間與實際公告時間分開，更正保留版本；不擴成完整財報產品。 |
| R1-F1 | 提案 | 當次 daily/backfill 明列的必要來源集合；條件式分點或未採用來源不作全域 blocker。 | 對所選來源做隔離 daily/backfill 重試、冪等、rate limit、觀測、備份與失敗通知；未准入／受限來源保持 unavailable 並從該 job 明確排除。排程本身需另行明確授權，且與自動交易分開。 |

Round09 R1-A1 有限 review 範圍與證據見 [SOURCE_REGISTRY](SOURCE_REGISTRY.md)：`STOCK_DAY_ALL`、`holidaySchedule`、`TWT48U_ALL`、`tpex_spendi_history` 的官方 Swagger／政府資料集／OGL 1.0 已逐筆核對；`local_fetch`、`raw_store`、`summarize` 是附條件 policy eligibility，`historical_pit` 因 first availability 與 revision snapshot 不足而 fail closed。數字 rate limit、精確發布時鐘、完整歷史起點、修訂與 endpoint-specific deprecation 未查到者維持 unknown。Round18 只讓同四筆可經 standalone executor 執行 `local_fetch + raw_store`；Round19／20 分別讓保存的單日 STOCK_DAY_ALL 與單年度 holiday bundle 進入兩個有限 library consumer；Round21–23 只修既有 today／history parser-consumer 的三個窄誤推論，Round24／25 再只修既有 TPEx action adapter 的 ratio/reference 與 cash precision，Round26 只為既有 TWSE action details 增加 API read-only classification，皆沒有新增第三個 capture consumer。D025-A／D026-A／D028-A 的保存或 bounded source evidence 只供各自 shape／contract review，不是 capture 接線或 availability truth；新增的 TPEx endpoints 也不是 Round09 新 registry admission，Round25／26 都沒有新網路或 source admission。`TWT48U_ALL`／`tpex_spendi_history` capture、paid subscription、TWSE reference／raw membership 與完整公司行動仍未接。整體 R1-A1、完整 legacy collector、summary、strict time evidence、舊資料 repair 與 PIT 保持未完成。

## 6. R2：候選與完整交易計畫

| ID | 狀態 | 小批與依賴 | 可驗收完成條件 |
| --- | --- | --- | --- |
| R2-A1 | 提案 | R1-C2；題材研究輸出。 | 同方法／窗口輸出強弱、熱度變化、廣度、領漲集中、延伸、籌碼分歧、事件方向與 coverage；原值與正規化值可追溯。 |
| R2-A2 | 提案 | 已准入且本批採用的事件／基本面來源；缺少或受限的面向可先明確為 unknown，不阻塞不依賴它的交易位置與持倉風險。 | 公司品質、事件機會、交易位置、持倉風險分開；矛盾可同時呈現，不硬湊單一「好股分數」，也不把 unknown 補 0。 |
| R2-B1 | 提案 | R0-C2、G-PRODUCT；trade-plan schema 與純計算。 | 觸發／確認、進場區間、不追價、失效、目標／移動停利、時間／事件失效、成本、tick、流動性、期限與版本俱全；無合法計畫可輸出不交易。 |
| R2-B2 | 提案 | R2-B1；執行與 lifecycle。 | 未觸發、到期、rejected_gap、無法成交、模擬成交、實際成交、退出與 incomparable 分開；stop 不保證成交；同日 stop／target 無順序不偏向有利結果。 |
| R2-C1 | 提案 | R2-B1、G-PRODUCT；部位與曝險。 | 使用精確股數；單筆／單股／同題材風險可追溯；同股多策略／多題材不重複占用；風險預算未知時不給張數。 |
| R2-C2 | 提案 | R2-A2、R2-C1；行動摘要。 | 同 exchange＋symbol＋as_of 一張卡；產品 A–E 合併矩陣全覆蓋；已驗證持倉風險優先，完整 observation 不被誤標資料待補。 |
| R2-D1 | 提案 | 本批已完成的 R2-A／B／C 能力；受限來源對應區塊顯示 unavailable，不延伸成假資料。 | `/news`、`/themes`、`/stocks`、`/actions` 的已接能力使用同版本與時間；中文標籤、來源、未知、單位與價位語意一致；診斷/raw 預設收合。 |
| R2-E1 | 提案 | R2-D1 與本批實際採用的來源／功能集合；條件式分點不作無關功能的 blocker。 | 零候選、缺資料、重疊題材、跳空、停牌、公司行動、修訂、持倉優先與多策略中適用案例可重跑；受限來源另驗 unavailable；production build、backend 全套與瀏覽器關鍵流程各自留證據。 |

## 7. R3：AI 與研究有效性

| ID | 狀態 | 小批與依賴 | 可驗收完成條件 |
| --- | --- | --- | --- |
| R3-A1 | 等待決策 | G-MODEL、G-PRODUCT。 | 在看 final test 前凍結 target event、H、trigger／fill、stop／target、成本、不可比、universe、split、metric、校準與採用門檻；文件有版本／hash。 |
| R3-A2 | 提案 | R3-A1 預先登錄的 feature set 所列、已准入且實際採用的來源；未列入或受限來源不作 blocker，也不得被模型暗中使用。 | 保存當時 universe（含下市／失敗標的）、來源與 membership 版本、input snapshot、available-at gate、label window；重疊持有期有 embargo／purge 規則；65 日資料不得冒充充分歷史。 |
| R3-B1 | 提案／可能受限 | R1-B2、G-SOURCE、G-MODEL；本地／免費事件理解基準。 | 先用人工標註小集評估來源忠實、引用、事件／關聯／方向與拒絕率；模型／提示／輸入 hash 可重現；無可用本地／免費模型時保留 deterministic baseline 並標 AI 能力 `受限`。 |
| R3-B2 | 提案 | R3-B1；事件理解接線。 | 結構驗證、prompt-injection 隔離、更正／撤回、低把握待核實與回退規則通過；摘要流暢度不算策略增益。 |
| R3-C1 | 提案 | R3-A2；量化基準。 | 先跑固定技術基準，再依序加入題材、新聞、籌碼、AI；同 universe／window／cost；所有嘗試與失敗保留，不挑最好結果後改門檻。 |
| R3-C2 | 提案 | R3-C1；walk-forward／OOS／校準。 | train、tune/calibration、final test 按時間隔離；報成本後報酬、回撤、尾損、成交率、有效樣本、coverage、不可比率及 Brier／校準；適用外或失敗時 probability 為 null。 |
| R3-D1 | 等待時間累積 | R3-A1、R2-E1；前瞻模擬。 | 每日先封存 snapshot、候選、plan、零候選、模型失敗及撤回，再等待 trigger 與 H／退出完成；不得回寫舊決策。等待長度與最低有效樣本由 R3-A1 事先決定，未達前保持 `等待`。 |
| R3-D2 | 等待樣本／市場狀態 | R3-D1；漂移與壓力期。 | 覆蓋事先要求的市場狀態與成本敏感度；來源中斷、模型失效及固定規則回退演練；日曆時間超過三個月本身仍不等於足夠。 |
| R3-E1 | 等待統籌決策 | R3-C2、R3-D2。 | 統籌依預先門檻做採用／拒絕／延長觀察；只有達標版本能候選成為預設，仍非投資保證；其餘保持 research-only。 |

## 8. 每輪更新方式

1. round 開始由統籌建立新的程式、文件、索引 task，並指定互不衝突的寫入範圍。
2. 實作 task 提供完整證據；文件 task 只把已核對事實回寫對應契約，不因「完成」訊息先標通過。
3. 統籌檢查差異、正式／隔離路徑與測試，再決定 `已 review`、修正或保持原狀。
4. 文件狀態只更新本批、ROADMAP 對應能力及必要操作限制；不以縮小原 scope 的方式把原 ROADMAP 宣稱完成。
5. 索引 task 更新本輪涉及分區並回報 coverage；索引成功不等於功能驗收。

Round 06 已完成 R0-B4／B3-persist 的有限 review；完成範圍只包含 caller-provided provenance 結構、schema 1 相容隔離保存，以及同日唯讀 legacy＋Wilder v2 兩 as-of 的 exact 離線比較。Round07 已完成 R0-C3／B5a 的 `time-evidence/v1` 本地核心／儲存 foundation；Round08 再完成分離的 `product-time/v1` News/API/UI read-time projection 與 legacy unknown 接線。Round09 已完成 R1-A1 的唯讀 registry／首批四個免費官方來源人工查證，Round18 再完成同四筆的有限 standalone capture executor，Round19／20 各接一個有限 consumer。Round12 C012 已完成 R0-B2 的分離 signal artifact pure/local store foundation；Round32 又完成有限 offline exact legacy／new descriptive comparison；Round33 再完成 caller-provided current pure-rule complete-argument capture/replay。這三個 R0-B2 slices 仍沒有共同的 artifact/subject/time/source/availability bridge或legacy-v2 paired execution；API/UI、worker、PIT 與 B7 仍未完成。後續依賴仍包含完整 legacy collector、source content／strict evidence、C007 產品／worker persistence linkage與 R0-B5/B3-wire。官方 source truth、B7、B4b 新 trade plan 及 R1–R3 中需要真實來源或前瞻時間的項目保持各自提案／等待，不能由 schema、介面、fixture、local export、HTTP 200、comparison report、rule bundle/digest、capture receipt 或 read-time projection 提前結案。
