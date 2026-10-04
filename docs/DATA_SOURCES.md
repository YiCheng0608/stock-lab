# 資料來源、coverage 與限制

更新：2026-10-04。本文件記錄來源、coverage 口徑與長期資料限制；能力狀態以 [ROADMAP](ROADMAP.md) 為準，逐來源授權、identity、用途與 probe 證據以 [SOURCE_REGISTRY](SOURCE_REGISTRY.md) 為準。歷史計數只描述表列日期的驗收結果，不能當成目前資料庫狀態。

## 資料庫政策

`collect`／`daily`／`backfill` 使用官方來源，SQLite 保存正規化市場資料、衍生研究資料與 raw 參照；沒有可信資料時顯示尚無資料。新增媒體、國際、分點或其他來源時，必須分開保存來源、版本、時間與推論，不能覆寫官方事實。source registry 本身不會自動改變 legacy collector。

正式 DB、`.local` DB、隔離資料與 migration 的操作邊界見 [操作手冊](OPERATIONS.md)。API startup 只執行有限唯讀 readiness；`worker.cli init-db` 才是明確 schema 建立／升級動作。

## 正式 data/stock.db：歷史 P0 結果

驗收日：2026-09-10。P0 市場窗口達標，但 global status 為 `partial`；下表是當時的有限 coverage，不是目前資料庫 snapshot。

| P0 證據 | 結果 | 限制 |
| --- | ---: | --- |
| verified TAIEX sessions | 65，`target_met=true` | 可作 1／5／20 日比較和 60 日策略窗口的共同基準。 |
| 明確 no-data／skipped | 2 | 不算有效交易日，也不補成行情。 |
| bars／chips | 149,770／148,346 | 須逐標的、日期與欄位檢查；單一標的完整不能外推全市場。 |
| 行情未達 20／60 日 | 244／333 檔 | 相關標的與群組策略結果為 `data_incomplete`。 |
| chips 未達 20／60 日 | 139／173 檔 | 不補 0；法人／融資 gate fail-closed。 |
| events | 65 sessions 全為 `unsupported` | 表示來源不能按日驗 empty；catalyst 為 null，不是 0。 |
| fundamentals | 65 sessions `partial` | 不是 v1 策略輸入，也不能稱完整。 |
| corporate actions | 2 `success`、63 `partial` | 缺可追溯調整時，價位／tracking 為 incomparable 或 `data_incomplete`。 |
| integrity／provenance | 當時檢查正常 | 不代表目前 DB 狀態。 |

Phase 3 的 P1 曾只規劃分析 2026-09-08；這是歷史作業範圍，不是所有未來分析的日期限制。現行 `analyze` 仍受最新 collect run gate 約束，沒有 per-as-of CLI。背景見 [PHASE3_PLAN](PHASE3_PLAN.md)，聚合契約見 [PRODUCT_SPEC](PRODUCT_SPEC.md#action-merge)。

## Official sources 與實作方式

| 資料域 | 官方來源／目前處理 |
| --- | --- |
| TWSE universe | [上市公司](https://openapi.twse.com.tw/v1/opendata/t187ap03_L)、[ETF](https://openapi.twse.com.tw/v1/opendata/t187ap47_L) 與新上市來源建立 allowlist。 |
| TPEx universe | [issuer master](https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O) 加 [ETF allowlist](https://info.tpex.org.tw/api/etfFilter) POST；混合 quote 的權證、CB、ETN、興櫃不 fallback 成 stock。 |
| TWSE OHLCV | 當日 [STOCK_DAY_ALL](https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL)；bounded history 為 [MI_INDEX](https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX)，依 allowlist 過濾。 |
| TPEx OHLCV | [dailyQuotes](https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes) POST，0–3 個月逐日擷取並依 stock／ETF allowlist 過濾。 |
| TWSE chips | 法人 [T86](https://www.twse.com.tw/rwd/zh/fund/T86)；融資 [MI_MARGN](https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN)。法人來源依外資及陸資、投信、自營商分類。 |
| TPEx chips | 既有 collector 法人 [dailyTrade](https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade)；融資 [balance](https://www.tpex.org.tw/www/zh-tw/margin/balance)。[三大法人買賣明細](https://www.tpex.org.tw/zh-tw/mainboard/trading/major-institutional/detail/day.html)明列外資及陸資、投信、自營商及合計。M1-P2a 的 exact [tpex_3insti_daily_trading](https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading) 單來源 manifest、用途准入與 capture／selected 摘要已有限 review；不自動放行 legacy collector。 |
| TPEx 多日法人／交易日 | 現行 W4獨立政府 CSV policy已有限接受3105／6488、9/29／9/30／10/1／10/2四截止的5／20日窗口、actual API及具名原生查看；union為8/31～10/2完整23開市日法人＋三月 index，僅 process memory，不改DB／legacy。來源／用途見[§15](SOURCE_REGISTRY.md#15-m1-w4四截止法人來源與全月日曆核對)，歷史W1／W3見§13／14。 |
| TWSE 券商／分點名冊 | [券商基本資料](https://openapi.twse.com.tw/v1/brokerService/brokerList)與[券商分公司基本資料](https://openapi.twse.com.tw/v1/opendata/OpenData_BRK02)為免費官方名冊；實際 GET 已確認可讀。名冊只提供通道身分，不是交易明細。 |
| 券商／分點人工查詢 | TWSE [券商買賣日報](https://bsr.twse.com.tw/bshtm/bsWelcome.aspx)涵蓋自營與受託交易並要求逐檔驗證碼；TPEx [券商買賣證券日報表查詢](https://www.tpex.org.tw/web/stock/aftertrading/broker_trading/brokerBS.php)只提供當日逐檔人工驗證。現行產品只導向官方入口，未整合資料。 |
| TAIEX | 官方指數資料，作 hot-group 超額報酬基準。 |
| MOPS／公司行動 | 重大訊息、基本面 snapshot 與 corporate actions；完整來源與 PIT 仍有限制。 |
| 停復牌 | TPEx [tpex_spendi_history](https://www.tpex.org.tw/openapi/v1/tpex_spendi_history) 已接可稽核 event；TWSE 完整歷史 coverage 尚不完整。 |
| raw provenance | 保存 endpoint、SHA-256、擷取時間與 data-as-of；正規化資料可回指 raw payload。 |

`STOCK_DAY_ALL`、`holidaySchedule`、`TWT48U_ALL`、`tpex_spendi_history` 是原 snapshot 四個已有限准入的 exact GET endpoint；M1-P2a 的 TPEx 日法人來源另需 explicit 單來源 manifest，不能沿用舊 default／version／pins。授權、用途 decision、capture 與 consumer 契約見 [SOURCE_REGISTRY](SOURCE_REGISTRY.md)，新增准入與待驗邊界見[第 8 節](SOURCE_REGISTRY.md#8-m1-p2atpex-日法人來源與-selected-摘要)。這些來源的數字 rate limit、精確發布時鐘、逐筆 first availability、完整 revision／withdrawal lineage 與 endpoint-specific deprecation 仍未知，`historical_pit` 均 unsupported；HTTP 200、今日 shape 或名稱含 `history` 都不能補足 PIT。

日常 UI 將官方「外資及陸資」合計欄位簡稱為「外資」，但 raw、來源與稽核層保留正式統計口徑；「三大法人」只指外資、投信與自營商，不能把廣義券商或分點另併為法人類別。

M1-P2a 的 TPEx selected 摘要以**股**為單位，外資及陸資採**不含外資自營商**欄位，投信、自營商分別計算，詳細欄位、合計 gate 與具名驗收見[來源契約 §8](SOURCE_REGISTRY.md#8-m1-p2atpex-日法人來源與-selected-摘要)。真實驗收只支持 **3105／6488、2026-10-02** 的單日 selected 數值與具名負向拒收；P2a 本身不代表 chips 表、總覽或 5／20 日窗口已接入。後續 M1-P2b 已有限 review 同兩檔原件→API 二十個數值及具名 UI 操作，提供明示設定的獨立單日區塊；精確契約見[個股頁 §10](STOCK_RESEARCH_PAGE.md#10-m1-p2b單日法人原件總覽接線)。不能將缺值補零，來源 `Date` 與單日列數也不證交易日曆；本批不改 DB／legacy 或 PIT 邊界。

後續 M1-W1 接受的 coverage 是**兩股、單一 cutoff、完整有界日曆及當次版本**，以原始成交為統計基礎，三類為外資（不含外資自營商）、投信、自營商合計，仍以股／canonical 整數字串呈現。缺日按各窗口 fail closed，不補零或縮窗；這不等於其他標的金融欄位、全市場／全年或歷史當時可得已驗證。published／first available／revision time unknown，`historical_pit=unsupported`，沒有磁碟原件／跨程序重開或研究條件接線。來源詳述與參考集中於[來源 §13](SOURCE_REGISTRY.md#13-m1-w1tpex-多日法人與完整有界交易日)，W2 操作見[個股頁 §18](STOCK_RESEARCH_PAGE.md#18-m1-w2同截止法人窗口與原件追溯)；不把舊候選或單日驗收升格。

W3歷史 coverage為兩股三 cutoff／22日曆，見[來源 §14](SOURCE_REGISTRY.md#14-m1-w3三截止法人來源與窗口)。現行 W4擴為**同兩股、四個明列 cutoff、有界23日曆與新 policy**，新增8/31 daily／8月 index；23 daily全列結構與兩股46 selected rows／1012金融欄檢核分開，不外推其他標的數值。三月43 index列全 OHLC先驗，8月21列中只採8/31、界線前20列已驗未採。窗口只採≤cutoff，缺／錯／壞日或競爭 revision按需該日的窗口拒用，不補零、縮窗或較早／未來替代。原始成交、股／canonical整數字串、未知發布／first availability／revision及非 PIT界線不變。現行版本與唯一48 net見[來源 §15](SOURCE_REGISTRY.md#15-m1-w4四截止法人來源與全月日曆核對)，具名操作／未驗邊界見[個股頁 §20](STOCK_RESEARCH_PAGE.md#20-m1-w4四截止法人窗口與原件追溯)；未保存 raw／跨程序讀回或接研究條件。8/28 daily僅 W5候選，未取得／准入，8月 OHLC已驗不授權取得該日法人。

News／Event 已有官方事件投影、來源連結、raw 稽核與時間欄位，但欄位存在不代表每筆來源時間可信。worker 尚未接完整媒體、國際新聞或分點資料；`ChipSnapshot` 雖定義當沖、融券與借券欄位，現有主要寫入路徑不能據此聲稱已收集。詳見 [NEWS_SPEC](NEWS_SPEC.md)。

## TAIEX session identity

R1-A2-P1-identity 的有限 review 僅確認：`verified_taiex_sessions` 的 TAIEX／TWII bar 與 backfill 日期報表 `taiex_rows` 的 index bar 計數，均新增 `exchange=TWSE` 條件；TPEx 同名 index 不得增加已核實 TAIEX session 分母、`taiex_rows` 或普通股票有效 bar 日。session 校驗原有的 active／index、日期範圍、provenance gate 與符合來源／日期條件的 raw MI_INDEX fallback 維持；`taiex_rows` 是報表列數或既有 raw fallback 指示，不能單獨視為已核實 session。合法 TWSE benchmark 仍是 TWSE／TPEx 普通股票共用的日期基準，並未建立兩市場各自的交易日曆。

這只修正 benchmark 的 exchange identity，未驗全市場或逐欄 coverage、真實官方 session、歷史完整性或 PIT。列數／日期數不能代表欄位用途可用；現行逐欄路徑與限制見下節。工作狀態見 [R1-A2](ROADMAP_EXECUTION.md)。

### R1-A2-P2+ 成交金額可得狀態（有限接受）

使用者已選定缺值政策：`turnover` 數值欄在來源成交金額缺失或無效時存 `0`，另以 `turnover_status`／`turnover_reason` 保存欄位狀態，不憑數值 `0` 判定來源真的為零。這是本地保存與使用契約，不代表 TWSE／TPEx 官方對缺值有相同定義。本輪程式範圍已獲統籌有限接受；尚未驗逐市場、逐標的、逐 session 的實際欄位 coverage 或官方歷史 payload。

| 路徑 | 已接受的成交金額契約 | 邊界 |
| --- | --- | --- |
| TWSE／TPEx 日行情 | [`parse_twse_daily_rows`／`parse_tpex_daily_rows`](../backend/worker/sources.py) 分別讀 `TradeValue`／`TransactionAmount`：缺失為 `turnover=0, status=unavailable, reason=missing`，無效為 `0, unavailable, invalid`；明確、可解析的非負數（含合法 `0`）為 `available`、reason 為 null。其餘有效 OHLC／volume 保留。 | 不把缺額列整筆拒收；欄位狀態不證官方原值或歷史完整性。legacy 成交量另由[精確整數 gate](#r1-a2-legacy-日行情成交量精確整數-gate有限接受)有限修復與驗收，成交額政策維持。 |
| opt-in selected `STOCK_DAY_ALL` capture | [`StockDayCapture.select`](../backend/worker/stock_day_capture.py) 保留既有 body／receipt／hash／日期 gate；選中列的 OHLC／volume 有效而 `TradeValue` 缺失或無效時，保留 bar 並給相同 `0 + unavailable + missing/invalid`。合法來源零為 `available`。adapter 可留成交額 unavailable warning。 | 純列 helper 與單一離線落盤 fixture 各有有限驗收，範圍見下段。指定三種 invalid／四類選列拒收的磁碟整合已有限接受，詳見下方專節；其他未覆蓋 invalid／拒收仍待驗。`TradeVolume` 仍要求精確非負整數；選中 symbol／OHLC／volume 缺失、無效或範圍不一致仍依原契約拒收。見 [SOURCE_REGISTRY §5.1](SOURCE_REGISTRY.md#51-stock_day_all-selected-security-bars)。 |
| TAIEX close-only | 指數 parser 合成的 `turnover=0` 標 `unavailable/synthetic_index`。close 補 O／H／L、volume 補 0 的既有路徑未在本批改成真實欄位。 | [`verified_taiex_sessions`](../backend/app/coverage.py) 的身分／日期／provenance gate 不證合成欄位可用；指數量額或 OHLC 不得由 session 列數升格。 |
| 保存、舊資料與重跑 | [`BarRecord`／`MarketBar`](../backend/app/models.py) 無來源證據時預設 `unknown`。[`_upsert_official_bar`](../backend/worker/pipeline.py) 保存數值、status 與 reason。`0007_turnover_availability` 和 fallback 升級對舊資料一次性分類：正值為 `available`；舊 `0` 為 `unknown/legacy_zero_ambiguous`；負值或 NULL 為 `unknown/legacy_invalid`。已有 status 的重跑不重分類或覆寫。 | 舊零無法還原為真零或缺值；legacy 磁碟 migration 的八案例已有限接受，精確 fixture／路徑及 NULL 限度見下節，正式 DB 升級未執行。既有資料不因新 parser 自動修復；migration 分類不證來源真相。 |
| API／TS／計算 | [`bar_dict`](../backend/app/api.py) 輸出 `turnover_status`（`available`／`unavailable`／`unknown`）及 nullable `turnover_reason`；[`Bar` 型別](../frontend/src/types.ts) 對齊。hot-group 與 strategy 兩種法人 flow ratio 只在所需各日 status 為 `available` 且成交額有效、為正時使用，否則回 unavailable。 | API 仍有數值 `turnover=0`；consumer 必須讀 status。未新增成交額 UI；其他特徵、TAIEX 合成 OHLC、逐欄 coverage 與 PIT 不因本批通過。 |

先前有限驗收使用可重建的離線 fixture，經 selected capture、collect force、實際落盤 SQLite 與新 session 讀回，再由 in-process API handler／serializer 回傳：TWSE selected 1101 缺額為 `0/unavailable/missing`，0050 明確零為 `0/available/null`，有效 OHLC／volume 保留。API startup readiness 在該測試被 bypass，故不證正式啟動或 deployment。指定三種 selected invalid／四類拒收另有下方有限磁碟驗收，本輪不重跑此缺額／明確零案例；其他未覆蓋 invalid／拒收、正式 DB 升級、官方真實逐欄 coverage 與 PIT 保持待驗。UI 空白與合法零的顯示契約見 [UI 文案 §10.4](UI_COPY_SPEC.md#104-數值表格單位與空白)。

#### R1-A2 legacy 成交額 migration 磁碟驗收（有限接受）

本輪已有限接受可重建 file-backed fixture 的關閉後讀回與失敗復原，支援 M1 資料可信與 R1 基線。兩條路徑分開驗收：Alembic 從明示 `0006_news_json_defaults` marker 升至 `0007_turnover_availability`，並拒絕偷偷改走 fallback；fallback-only 從已知完整 `schema_migrations` 0001→0006 升至 0007，沒有 `alembic_version` 表，不把它當 Alembic current 或 API readiness 證據。

fixture 先複製目前 canonical metadata 建立空 schema，只移除 0007 的 `turnover_status`／`turnover_reason` 兩欄，再設定上述 marker；已有 status 的案例保留兩欄。每案例 seed 一個 instrument、一筆 raw metadata 與三筆 bar，NULL variant 為四筆。raw 的 `payload_path`／`sha256` 為 NULL，未保存或複製原件 body、既有 DB 或真實來源樣本；這是 synthetic shape，不證所有歷史 0006 DB 可升級。

| 每條路徑的案例 | 已驗收的有限行為 |
| --- | --- |
| legacy 正值／零／負值 | 正值為 `available/null`；零為 `unknown/legacy_zero_ambiguous`；負值為 `unknown/legacy_invalid`。關閉 engine、新 engine 讀回及再升級後結果一致。 |
| synthetic nullable NULL | 只在獨立複製的 metadata 將 `turnover` 改為 nullable，NULL 分類為 `unknown/legacy_invalid`，關閉後讀回及重跑保留。目前 ORM 欄仍不可為 NULL，不推論正式 DB 的 nullable 形狀。 |
| 起始已有 status／reason | 保留既存狀態與原因，包括與舊數值分類不同的明示狀態；關閉後讀回與重跑不覆寫。 |
| trigger 中止與同檔重試 | 本測試 trigger 中止 backfill 後，重開確認原資料、完整 schema 及 markers 回復，availability 欄未留下、marker 未前進；只移除本測試 trigger，在同一 fixture 檔重試成功，再重開與重跑核對。這不授權刪除任意 DB trigger 來修復。 |

八個案例核對原 instruments／raw_payloads／market_bars 的 typed 值與 typeof、欄描述／indexes／FK、關聯、重開 integrity／FK 與路徑 markers，已有限接受；不代表所有歷史 0006 schema。建構方式見[專用測試](../backend/tests/test_turnover_availability_file_migration.py)，入口／配額／清理由[開發文件](development-baseline/README.md#r1-a2-legacy-成交額-migration-的磁碟驗證入口)負責；實際命令、exit 與收據留 task。

本批未改產品來源，未跑完整 backend、API startup、UI、正式 DB 升級、backup restore 或 deployment，也未抓外網。這只解除上述兩路徑的磁碟讀回／失敗復原驗證缺口；官方逐市場／逐欄 coverage、歷史／availability／PIT、完整 5／20 日窗口及 TAIEX 合成欄位等原 gate 不變。後續指定 selected invalid／拒收的有限磁碟驗收見下節；兩批證據分開，不互相外推。

[TWSE OpenAPI](https://openapi.twse.com.tw/) 僅作端點／欄位線索；[A05 商品規格](https://eshop.twse.com.tw/zh/product/detail/cfec9a1470e448ec91bfde006db361e8) 的內部使用標價 NT$1,000／月只供唯讀辨識其受費用限制，並非本專案資料來源、下載、授權或驗收證據。本輪未抓官方 payload。

#### R1-A2 selected invalid／拒收磁碟整合（有限接受）

本輪已有限接受一個 compound unittest，以可重建的離線 unsigned synthetic `STOCK_DAY_ALL` fixture 支援 M1 研究資料可信與 R1-A2 基線，解除以下指定 subset 的磁碟整合缺口。fixture 為 **2026-09-04、十一個 synthetic selected 標的**；走既有 `source_runtime.capture(MockTransport)`→load／select→`TwseAdapter.fetch`→`OfficialMarketDataAdapter.fetch` 按既有 key 正常去重→`pipeline.collect(force)`，再 dispose、以新 `NullPool` engine 讀回同一 SQLite 檔，經 production `api.router`／handler／serializer 核對十一個 HTTP 回應。原 body／receipt／hash／日期 gate 保留，未改產品來源、consumer 或 pins。

| 指定案例 | 已驗收的有限行為 |
| --- | --- |
| `TradeValue=-1`、`12xyz`、`12,34` | 三種無效成交額各保留有效 OHLC／volume，成交額為 `0/unavailable/invalid`，關閉後讀回及 API 一致。 |
| `missing_symbol`、`OpeningPrice` 空、`TradeVolume=1.5`、OHLC 範圍不一致 | 四類拒收各覆蓋 existing／empty 兩種情境，共八個 selected 標的；四筆既存 bar 的 typed 欄值、id、raw 關聯及 status／reason 保留，四個原無 bar 標的仍無 bar、API 為空，不被另有有效列的 MI_INDEX history fallback 補值。 |

重開另核三筆 accepted bar 的 target raw source／endpoint／body path／hash、UTC capture、data_as_of、run FK 與 partial 狀態；原 raw typed 值及 ZIP／body／receipt hash 不變，integrity／FK 正常，再次 select 仍拒相同列。第三次 compound unittest 已有限接受；早期實測／policy 失敗與成功收據留 task，不稱首跑通過。

這是一個組合測試內的指定三種 invalid 與四類拒收斷言，不是十一個獨立 unittest，也不涵蓋其他 invalid 或全域拒收。其他端點的 payload／capture metadata 以記憶體 fixture 提供，包含 collector 所需 synthetic MI_INDEX／session；TPEx 只給明示空 `OfficialBatch` 邊界，不作真實官方資料、TPEx 或全域 coverage 證據。API 核對也不證完整啟動、UI、正式 DB 或 deployment；未取得真官方樣本，不放行歷史／availability／PIT、完整 5／20 日窗口或其餘逐欄 gate。selected 整數 gate 的證據不外推 legacy；legacy 日行情成交量另有下方[精確整數 gate](#r1-a2-legacy-日行情成交量精確整數-gate有限接受)的本地有限修復及驗收。

建構方式留[專用測試](../backend/tests/test_stock_day_selected_invalid_file_integration.py)；runner 副作用、落盤配額及測試／清理分報由[開發入口](development-baseline/README.md#r1-a2-selected-invalid拒收的磁碟驗證入口)詳述。完整 backend、production API startup／lifespan、UI、live 官方來源、TPEx、正式 DB 與 migration 八案例均未跑，不外推通過；命令／版本及逐 run 數值留原 task，不另建附件。

### R1-A2 legacy 日行情成交量精確整數 gate（有限接受）

本輪已有限接受 [`parse_twse_daily_rows`／`parse_tpex_daily_rows`](../backend/worker/sources.py) 的專用成交量讀取及 TPEx 合法空結果條件，支援 M1 研究資料可信／R1-A2 基線。成交量以**股**為單位，直接從原值型別判讀，避免先轉浮點再取整；有效輸出為 Python `int`，範圍 **0–9,223,372,036,854,775,807**。缺失或無效成交量拒收該筆 bar，不補零或保留截整值；合法來源零仍保留。

| 原值或欄位條件 | 契約 |
| --- | --- |
| 別名順序 | TWSE 依 `TradeVolume`→`成交股數`→`成交量`；TPEx 依 `TradingShares`→`成交股數`→`成交量`。僅 `None` 或空白字串可改讀下一欄；第一個非空值即決定結果，合法 `0` 不被跳過，無效主欄不以其他別名補值。 |
| 整數及 Decimal | 接受非 bool 的 `int`，或有限、非負、數學值為整數且未超上限的 `Decimal`；typed `Decimal("1E+3")` 可為 1000，`Decimal("-0")` 可為 0。 |
| 字串 | 去除前後空白後須完整匹配 ASCII 十進位數字；可含開頭 `+`、前導零、正確千分逗號（首組 1–3 位、後續每組 3 位），以及小數點後全部為零的完整小數部分。例如 `+1,234.000` 為 1234。 |
| 拒收 | 所有 float（含 `0.0`／`1234.0`）、bool、容器及其他型別；負值、非整數、NaN／Infinity、超上限；字串科學記號、負號、夾字、錯誤分組、內部空白或不完整數值均拒收。`1.9`、`12xyz`、`12,34` 不再分別變成 1、12、1234。 |
| 大整數及既有欄位 | `9,007,199,254,740,993` 與 64-bit 上限的允許型別保持精確，不經 float；日期、symbol、來源 metadata、OHLC 及成交額 availability 保留原處理，共用 `parse_integer`、MOPS 與 selected 契約未改。 |
| TPEx 空結果 | 既有 reported-date gate 通過後，只有無 tabular rows 的 payload 可加入 `no_data_dates`；非空但全部被拒收的表格不代表合法空日。原日期缺失／不符與 prior-session 守門條件保留。 |

有限驗收使用 **2026-09-04 synthetic fixture**，prior-session 另含 **2026-09-03**；[專用測試](../backend/tests/test_legacy_daily_volume.py)涵蓋兩 parser、row／table wrappers、TWSE MI_INDEX history 與兩市場 fetch_bars 的具名拒收。另有低 Decimal precision 4 數值複核。adapter _fetch 以 memory payload／metadata 替換，未 capture 或持久化；[零落盤入口](development-baseline/README.md#r1-a2-legacy-成交量的零落盤驗證入口)負責隔離與 I/O，計數／exit／收據留 task。

這只解除上述 parser／adapter fixture 的精確整數與錯誤空結果缺口，不代表該批已驗 collect、SQLite 關閉後讀回、API、live 官方來源、UI、production startup 或完整 backend，也不自動修復舊資料。後續[legacy 成交量磁碟整合](#r1-a2-legacy-成交量磁碟整合)已有下方具名有限驗收；正式 DB、官方逐市場／逐欄 coverage、歷史／availability、完整 5／20 日與 PIT gate 不變。

### R1-A2 legacy 成交量磁碟整合

已有限接受 legacy 成交量 gate→capture／collect／SQLite 重開／API 的指定整數精確保存與拒收保留，支援 M1／R1-A2。[專用測試](../backend/tests/test_legacy_daily_volume_file_integration.py)是一個 compound unittest，兩次 force collect 的具名範圍見下表；產品來源與 pins 未改，沿用證據不作重新驗收。

fixture 為固定 **2026-09-04** 的兩市場共 **30 個 synthetic symbols**；每次 collect 的三個目標 capture 走 production pass-through 保存，兩次共六個，capture 固定日期為 **2026-09-05**。TWSE current 與 MI_INDEX 對同一拒收標的提供相同無效成交量，不使用 selected capture；TWSE／TPEx 均經真正 adapter 與 combined adapter。其他 collector 必要 payload／metadata 以記憶體 fixture 提供，不作真實官方來源證據。

| 指定案例 | 已驗收的有限行為 |
| --- | --- |
| TWSE／TPEx 各 `0`、`9007199254740993`、`9223372036854775807` | 共六個合法標的，capture／collect 後的 SQLite `typeof(volume)=integer`、Python `int` 及 API HTTP 原始整數 token 保持精確；合法零不作缺值，既有 OHLC／成交額狀態一致。 |
| 每市場各字串 `1.5`、`-1`、`12,34`、`9223372036854775808`，以及 JSON `true`／`1234.0` | 六類拒收各覆蓋 existing／empty 兩情境，共 24 個拒收標的；existing bar 原有 typed 值與 raw 關聯保留，empty 不產生 bar，不被 TWSE MI_INDEX fallback 補值。 |
| 同一單日兩次 `collect(force)` | 首次為 `partial`、`records=7`（六筆股票及一筆 TAIEX）；第二次兩市場股票全部 invalid、仍有有效 TAIEX，但 run 為 `failed`、`records=0`、`no_data_dates=[]`。全部 19 筆 bar（六筆合法、十二筆 existing 與 TAIEX）及原 raw 的完整 typed 值保留，十二個 empty 仍無 bar；failed attempt 可回指第二次 raw。 |
| dispose 後新 `NullPool` engine／current DB 讀回及 HTTP API | 由空的 current DB 正常初始化 0001→0007，再真正重開同一 SQLite 檔，核對上述合法整數與拒收保留；30 個標的兩輪各一個 HTTP 回應，共 60 個，raw HTTP int token 精確。兩次重開均 `integrity_check=ok`、`foreign_key_check` 無列。 |

六個 target captures 的 encoded bytes／hash／metadata 與 DB 關聯已核，第一批原 bytes 不變。測試與清理均 exit 0，核定根不存在；載入前 execution-policy 拒絕未啟動 runner，不算成功命令，原證據留 task。

fixture JSON 不含 Decimal；這只解除上述指定整數、拒收與保存路徑的磁碟證據缺口，不把 capture fixture 升格官方原件，也不證 JavaScript／browser 能精確保留大整數。真官方／live、UI、production startup、完整 backend、正式 DB、Decimal capture、PIT 或完整 5／20 日窗口均未驗；其他 invalid／拒收及逐市場／逐欄 coverage 保持待驗，不升格完整 R1-A2。落盤根、配額、入口副作用與清理由[開發入口](development-baseline/README.md#r1-a2-legacy-成交量的磁碟整合驗證入口)詳述；版本、實測命令、原始收據與下一步評估留 task／[ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑)。

## 0–3 個月隔離收集驗證

歷史隔離驗收範圍為 2026-06-10 至 2026-09-08、official-only，結果為 `partial`。有限證據只支持 TPEx 三個月 OHLCV、法人、融資、raw provenance 與相同 request 重跑不產生 duplicate／orphan；不表示兩市場歷史完整，也不表示正式 DB 擁有相同 coverage。

## v1 資料規則與歷史來源限制

- `--months-back` 只允許 0、1、2、3；1–3 個月先在隔離 DB 檢查 run status、data quality 與 raw evidence。
- TWSE 明確 no-data 且無列可略過；錯日、缺日或日期不可驗的 payload fail-closed，不映射到其他交易日。
- 歷史 TWSE `MI_INDEX`／CDN、`T86`／`MI_MARGN` 曾在部分日期回 307／428；2026-09-08 的 `MI_MARGN` 也缺可驗證日期。因此三個月 run 是 partial，歷史 chips 不得稱完整。
- chips 已接入；任一市場、日期、欄位或 allowlisted 標的缺完整法人／融資時，不補 0，策略結果為 `data_incomplete`。
- P0 events 的 65 sessions 是 unsupported；只有其他 component 完整且同榜 event coverage 一致 unsupported 時，才能呈現不稱熱門的技術／籌碼觀察。
- ETF 收集、分類並進 ETF 分榜；bond、leveraged、inverse 只排除一般 v1 actionable signal，不排除資料或排行。
- TPEx suspension history 已接入；TWSE 完整歷史不足時 tracking 仍可為 incomparable。

## 資料庫安全

程式 migration head、實際 DB revision 與 preservation 證據由 [R0 §8](R0_IMPLEMENTATION.md#8-r0-5migration-head-與實際-db-revision) 維護，不能由 coverage 推論。API startup 只做有限唯讀 readiness；明確 schema mutation、backup、隔離演練與 restore／deployment 順序見 [操作手冊](OPERATIONS.md#2-資料庫migration-與-readiness)。

## 下一版資料需求與可得性

下表是需求，不是已接入或已確認 coverage。

| 資料 | 優先目的 | 必須確認／保存 |
| --- | --- | --- |
| 行情、TAIEX、公司行動、停牌 | 價格特徵、執行與回測 | 交易日、標的、調整基礎、原始／修訂版本、停復牌與缺口。 |
| 分類法人 | 資金持續性與分歧 | 投資人別、買賣淨額單位與官方定義。 |
| 現股當沖 | 短線活躍度 | 股數／金額口徑、首次公布與 T+1／T+2 修訂。 |
| 券商／分點 | 集中度與反轉特徵 | 官方網站可免費逐檔人工查詢，但需驗證碼，TPEx 頁面只提供當日；仍須確認可機器使用的合法來源、量價、歷史範圍、權限與費用，且不能識別投資人。 |
| 融券／借券／持股 | 籌碼風險 | 定義、更新頻率、可得時間與市場範圍。 |
| 財報／營收／公告 | 公司品質與事件 | 會計期間、實際公告時間及更正版本。 |
| 宏觀、媒體、國際事件 | 題材與新資訊 | 原文、使用條件、發布／可得時間、去重與影響證據。 |
| 題材 membership | 跨產業研究 | 多重歸屬、證據、相關程度、生效／失效時間與版本。 |

分點是自營或受託交易通道彙總，不能由名稱推定資金國籍、同一投資人、所謂「主力」或隔日沖意圖。2026-09-15 的官方頁查證只支持免費人工查詢入口，不支持已取得可整合的分點交易 API、歷史資料集或 coverage；因此 UI 可連往 TWSE／TPEx 查詢頁，不能顯示虛構分點數值或主力排行。當沖統計可能到 T+2 修訂，資料設計仍須保留當時版本；原資料定義見 [TPEx 當沖說明](https://www.tpex.org.tw/storage/zh-tw/web/stock/trading/intraday_stat/intraday_trading_statY.htm)。

### 券商分點與主力統計的來源邊界（後續待做）

- 官方券商／分點名冊提供券商／分點代號與名稱，但不含買賣交易；歷史更名與券商隸屬仍待驗證。官方逐檔交易查詢需要人工驗證；可評估在使用條件允許下匯入合法取得的 CSV，但尚未實作，也不能先承諾完整免費自動歷史。
- [FinMind TaiwanStockTradingDailyReport 文件](https://finmind.github.io/tutor/TaiwanMarket/Chip/)列為 Sponsor 方案，說明歷史自 2021-06-30 起且有已知缺日。它目前只是候選，未採購、未接入，也沒有取得授權的結論。
- CMoney 的[主力進出參考](https://www.cmoney.tw/forum/stock/8039?s=main-force)與[市場表格](https://www.cmoney.com.tw/M_Table.aspx?CMenuID=M668)可用來理解「Top 15 買超合計減 Top 15 賣超合計」的觀念；不承諾本產品數值相同。精確期間、選樣、家數差與 5／20 日集中度口徑須在實作前版本化核定。

以上來源盤點不等於交易資料已接入。後續功能以[個股頁籌碼三部分](STOCK_RESEARCH_PAGE.md#8-籌碼三部分後續待做)為準；缺資料仍留空，「主力」是可重現分點統計而非身分判定。

## 時間、版本與研究窗口（目標契約）

- `market_date`／`event_date` 描述資料日期，不代表何時可用。
- `published_at`／`first_available_at` 分別是來源發布與首次可取得時間；無證據時標 unknown。
- `collected_at` 是本系統取得時間，不能把回補日反推成歷史可得日。
- `revision_available_at`／`supersedes` 保存更正的可得時間與被替代版本；原版保留。
- `decision_at`／`generated_at` 分開；最早執行不得早於必要資料可得時間與策略允許的下一交易時段。
- as-of 查詢只讀當時可得的資料與 membership，正式可用版本與事後修訂分開保存。

legacy `signal.data_cutoff` 的 13:30 字串不證明所有盤後資料當時已知。新長期研究須先定義 universe、下市／停牌、版本、coverage 與費用；現行 collect 0–3 個月與 backfill 93 日上限不因文件更新而放寬。
