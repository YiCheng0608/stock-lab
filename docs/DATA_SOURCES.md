# 資料來源、coverage 與限制

更新：2026-09-16。本文件記錄來源、coverage 口徑與長期資料限制；能力狀態以 [ROADMAP](ROADMAP.md) 為準，逐來源授權、identity、用途與 probe 證據以 [SOURCE_REGISTRY](SOURCE_REGISTRY.md) 為準。歷史計數只描述表列日期的驗收結果，不能當成目前資料庫狀態。

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
| TPEx chips | 法人 [dailyTrade](https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade)；融資 [balance](https://www.tpex.org.tw/www/zh-tw/margin/balance)。[三大法人買賣明細](https://www.tpex.org.tw/zh-tw/mainboard/trading/major-institutional/detail/day.html)明列外資及陸資、投信、自營商及合計。 |
| TWSE 券商／分點名冊 | [券商基本資料](https://openapi.twse.com.tw/v1/brokerService/brokerList)與[券商分公司基本資料](https://openapi.twse.com.tw/v1/opendata/OpenData_BRK02)為免費官方名冊；實際 GET 已確認可讀。名冊只提供通道身分，不是交易明細。 |
| 券商／分點人工查詢 | TWSE [券商買賣日報](https://bsr.twse.com.tw/bshtm/bsWelcome.aspx)涵蓋自營與受託交易並要求逐檔驗證碼；TPEx [券商買賣證券日報表查詢](https://www.tpex.org.tw/web/stock/aftertrading/broker_trading/brokerBS.php)只提供當日逐檔人工驗證。現行產品只導向官方入口，未整合資料。 |
| TAIEX | 官方指數資料，作 hot-group 超額報酬基準。 |
| MOPS／公司行動 | 重大訊息、基本面 snapshot 與 corporate actions；完整來源與 PIT 仍有限制。 |
| 停復牌 | TPEx [tpex_spendi_history](https://www.tpex.org.tw/openapi/v1/tpex_spendi_history) 已接可稽核 event；TWSE 完整歷史 coverage 尚不完整。 |
| raw provenance | 保存 endpoint、SHA-256、擷取時間與 data-as-of；正規化資料可回指 raw payload。 |

`STOCK_DAY_ALL`、`holidaySchedule`、`TWT48U_ALL`、`tpex_spendi_history` 四個 exact GET endpoint 已有限准入；授權、用途 decision、capture 與 consumer 契約見 [SOURCE_REGISTRY](SOURCE_REGISTRY.md)。四者的數字 rate limit、精確發布時鐘、逐筆 first availability、完整 revision／withdrawal lineage 與 endpoint-specific deprecation 仍未知，`historical_pit` 均 unsupported；HTTP 200、今日 shape 或名稱含 `history` 都不能補足 PIT。

日常 UI 將官方「外資及陸資」合計欄位簡稱為「外資」，但 raw、來源與稽核層保留正式統計口徑；「三大法人」只指外資、投信與自營商，不能把廣義券商或分點另併為法人類別。

News／Event 已有官方事件投影、來源連結、raw 稽核與時間欄位，但欄位存在不代表每筆來源時間可信。worker 尚未接完整媒體、國際新聞或分點資料；`ChipSnapshot` 雖定義當沖、融券與借券欄位，現有主要寫入路徑不能據此聲稱已收集。詳見 [NEWS_SPEC](NEWS_SPEC.md)。

## TAIEX session identity

R1-A2-P1-identity 的有限 review 僅確認：`verified_taiex_sessions` 的 TAIEX／TWII bar 與 backfill 日期報表 `taiex_rows` 的 index bar 計數，均新增 `exchange=TWSE` 條件；TPEx 同名 index 不得增加已核實 TAIEX session 分母、`taiex_rows` 或普通股票有效 bar 日。session 校驗原有的 active／index、日期範圍、provenance gate 與符合來源／日期條件的 raw MI_INDEX fallback 維持；`taiex_rows` 是報表列數或既有 raw fallback 指示，不能單獨視為已核實 session。合法 TWSE benchmark 仍是 TWSE／TPEx 普通股票共用的日期基準，並未建立兩市場各自的交易日曆。

這只修正 benchmark 的 exchange identity，未驗全市場或逐欄 coverage、真實官方 session、歷史完整性或 PIT。列數／日期數不能代表欄位用途可用：現有 TAIEX close-only parser 以 close 填 O／H／L、量額填 0；legacy 缺 `TradeValue` 時 `turnover=0`，`TradeVolume` 小數可能截整。這些欄位的來源、model／schema、storage 與 consumer 用途仍須逐一核查；不得把合成值或缺值當作已驗證的官方欄位。工作狀態見 [R1-A2](ROADMAP_EXECUTION.md)。

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
