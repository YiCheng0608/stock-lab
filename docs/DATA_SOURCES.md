# 資料來源與限制

本文記錄資料來源、保存規則與已知限制；能力狀態以 [ROADMAP](ROADMAP.md) 為準。

## 來源選用原則

專案只用免費公開資料。依 [ROADMAP V1 基線](ROADMAP.md#v1-範圍基線2026-10-17-核定)，每日全市場行情、法人、融資與官方事件以官方 TWSE／TPEx 整批下載為主要來源；FinMind 免費方案補歷史回補與缺口（規則見[下節](#finmind-補缺口規則)），官方與 FinMind 都沒有的資料集才另提來源；新聞用免費公開的國內外媒體與官方來源，依 [NEWS_SPEC](NEWS_SPEC.md) 分開保存來源、時間與推論。新增來源前先在 Issue 記錄端點、欄位、授權、用途與限制。

## 資料庫政策

`collect`／`daily`／`backfill` 使用官方來源，SQLite 保存正規化市場資料、衍生研究資料與 raw 參照；缺資料的顯示依 [ROADMAP 顯示原則](ROADMAP.md#v1-範圍基線2026-10-17-核定)。新增媒體、國際或其他來源時，必須分開保存來源、版本、時間與推論，不能覆寫官方事實。DB 路徑、migration 與 readiness 見[操作手冊](OPERATIONS.md)。

## 官方來源

端點常數定義在 [`backend/worker/sources.py`](../backend/worker/sources.py)；下表只列 collector 實際呼叫的端點。

| 資料域 | 端點 | 用途與處理 | 限制 |
| --- | --- | --- | --- |
| TWSE universe | [上市公司 `t187ap03_L`](https://openapi.twse.com.tw/v1/opendata/t187ap03_L)、[ETF `t187ap47_L`](https://openapi.twse.com.tw/v1/opendata/t187ap47_L)、[新上市 `company/newlisting`](https://openapi.twse.com.tw/v1/company/newlisting) | 建立上市普通股與 ETF allowlist；數字代號 ETF 以 `t187ap47_L` 辨識。 | 名單是取得當下狀態，不含歷史上下市版本。 |
| TPEx universe | [issuer master `mopsfin_t187ap03_O`](https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O)、[ETF allowlist `etfFilter`](https://info.tpex.org.tw/api/etfFilter)（POST） | 建立上櫃普通股與 ETF allowlist。 | 混合行情中的權證、CB、ETN、興櫃不當成股票；興櫃 feed 不用來建 universe。 |
| TWSE 日行情 | 當日 [`STOCK_DAY_ALL`](https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL)；歷史 [`MI_INDEX`](https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX)（單日全市場表） | 依 allowlist 過濾，讀 OHLC、`TradeVolume`（股）、`TradeValue`。歷史以逐日全市場表回補，不逐檔逐月請求。 | 明確 no-data 且無列可略過；錯日、缺日或日期不可驗的 payload fail-closed，不映射到其他交易日。 |
| TWSE 交易日曆 | [`holidaySchedule`](https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule) | 多日回補時作正面排除清單：明列休市日不送 `MI_INDEX`。 | 取得失敗不推論休市，該日照常請求並 fail-closed；只描述年度最新版本，不是歷史版本。 |
| TAIEX | 當日 [`exchangeReport/MI_INDEX`](https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX)；歷史取自 `MI_INDEX` 全市場表 | 加權指數作 hot-group 超額報酬基準與交易日基準（見 [TAIEX 交易日基準](#taiex-交易日基準)）。 | 只有收盤值；合成的 O／H／L、成交量與成交額不是真實欄位。 |
| TPEx 日行情 | [`dailyQuotes`](https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes)（POST） | 逐日擷取並依股票／ETF allowlist 過濾，讀 OHLC、`TradingShares`（股）、`TransactionAmount`。 | 回報日期須等於請求日期；非空但全部被拒收的表格不算合法空日。 |
| TWSE 籌碼 | 法人 [`T86`](https://www.twse.com.tw/rwd/zh/fund/T86)；融資 [`MI_MARGN`](https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN) | 法人依外資及陸資、投信、自營商分類；融資讀餘額與增減。 | 請求可能被限流、重導或缺可驗證日期。 |
| TPEx 籌碼 | 法人 [`insti/dailyTrade`](https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade)；融資 [`margin/balance`](https://www.tpex.org.tw/www/zh-tw/margin/balance) | 同 TWSE 口徑；[三大法人買賣明細](https://www.tpex.org.tw/zh-tw/mainboard/trading/major-institutional/detail/day.html)明列外資及陸資、投信、自營商及合計。 | 缺資料時不補 0。 |
| 公司行動 | TWSE [`TWT48U_ALL`](https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL)；TPEx [`tpex_exright_daily`](https://www.tpex.org.tw/openapi/v1/tpex_exright_daily) | 除權息資料寫入 corporate actions，作價格調整與追蹤比較。 | `TWT48U_ALL` 可含未來預告，須保存擷取時間；完整歷史與更正紀錄不明。欄位規則見[公司行動欄位](#公司行動欄位)。 |
| 停復牌 | TPEx [`tpex_spendi_today`](https://www.tpex.org.tw/openapi/v1/tpex_spendi_today)、[`tpex_spendi_history`](https://www.tpex.org.tw/openapi/v1/tpex_spendi_history) | history 轉為可稽核的停牌區間事件；區間內缺 bar 視為不可比。 | today 同時列暫停與恢復公告，代號存在不等於仍停牌；TWSE 停牌歷史未接入，追蹤可能為不可比。見[停復牌規則](#tpex-停復牌規則)。 |
| 重大訊息／基本面 | TWSE [`t187ap04_L`](https://openapi.twse.com.tw/v1/opendata/t187ap04_L)、[`t187ap14_L`](https://openapi.twse.com.tw/v1/opendata/t187ap14_L)；TPEx [`mopsfin_t187ap04_O`](https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O)、[`mopsfin_t187ap14_O`](https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap14_O) | 官方事件與基本面 snapshot。 | 只是取得當下的 snapshot，不能重建歷史可得時間；基本面不是 v1 策略輸入。同股同日多則不同公告標題相同時，以發言時間區分：最早一則保留原標題，之後各則標題加「（發言時間 HH:MM:SS）」（內容完全相同的重複列只留一則），之後重抓不會改名已存的事件。 |

每筆 raw 保存 endpoint、SHA-256、擷取時間與 data-as-of；正規化資料可回指 raw payload：日線與籌碼列指向第一次寫入（或 `force` 覆寫）的 capture，之後重抓只補空欄時不改指向，補值的來源記在 collect run 的 `value_fill_groups`（[OPERATIONS §6.4](OPERATIONS.md#64-重跑與回補)）。News／Event 有官方事件投影、來源連結、raw 稽核與時間欄位，但欄位存在不代表每筆來源時間可信，詳見 [NEWS_SPEC](NEWS_SPEC.md)。`ChipSnapshot` 雖定義當沖、融券與借券欄位，現有寫入路徑不收集這些值。券商分點列後版，collector 不接入。

### 核心與非核心來源

collect 的狀態只看核心來源：日行情（`STOCK_DAY_ALL`、`MI_INDEX`、`dailyQuotes`）、TAIEX、交易日曆、法人與融資。它們的 warning 讓 collect 變 `partial`，daily 不跑 analyze。重大訊息與基本面（`t187ap04_L`、`t187ap14_L`、`mopsfin_t187ap04_O`、`mopsfin_t187ap14_O`）及 TPEx 停復牌（`tpex_spendi_today`、`tpex_spendi_history`）是非核心：取得失敗記為 `noncore_warnings`，collect 仍為 `success`，缺的事件與基本面照「缺資料留空」處理（`mops_events`／`mops_fundamentals` 的資料品質列為 `partial`）。分類依 warning 文字（`pipeline.NONCORE_WARNING_PATTERN`），新增來源的 warning 未列入前一律算核心。

## 官方來源共同限制

- [TWSE Swagger](https://openapi.twse.com.tw/v1/swagger.json)（`basePath=/v1`）與 [TPEx Swagger](https://www.tpex.org.tw/openapi/swagger.json)（server `https://www.tpex.org.tw/openapi/v1`）是 OpenAPI 端點與欄位的參考。
- OpenAPI 資料集標示免費並採[政府資料開放授權條款第 1 版](https://data.gov.tw/license)；raw 保存與摘要須顯名、保留來源完整性與可追溯性。授權不等於 endpoint SLA。
- [TWSE 使用條款](https://www.twse.com.tw/zh/terms/use.html)限制未經同意的自動下載，collector 只做有上限的批次請求；[TPEx 條款](https://www.tpex.org.tw/zh-tw/gtsm_disclaimer.html?l=zh-tw)要求引用標示來源並維持完整性。
- 各端點的數字 rate limit、精確發布時間、逐筆首次可得時間、修訂／撤回紀錄與停用通知都未公開；一次 HTTP 200、今日的 payload 形狀或名稱含「history」都不能證明歷史可重建。
- TWSE 的 [A05 付費商品](https://eshop.twse.com.tw/zh/product/detail/cfec9a1470e448ec91bfde006db361e8) 不是本專案資料來源。

## 新聞來源

`python -m worker.cli news` 讀取下表的 RSS feed（登錄在 [`backend/worker/news_sources.py`](../backend/worker/news_sources.py)），不抓正文，也不收付費或需登入的來源。用途限本機個人非商業研究，顯示時標示來源名稱。

| 來源 | `source_kind`／`category` | endpoint | 使用條件 | 保存欄位 | 頻率 | 延遲 |
| --- | --- | --- | --- | --- | --- | --- |
| 中央社 產經證券 | `media`／`domestic` | [`feeds.feedburner.com/rsscna/finance`](https://feeds.feedburner.com/rsscna/finance) | [RSS 規範](https://www.cna.com.tw/about/rss.aspx)：個人、非營利之非商業用途，標示「中央通訊社」，不得引用全文 | 標題、前言（`summary`）、pubDate、guid、單篇連結 | 每 2 小時；feed 約 20 則 | ttl 15 分＋排程間隔，最多約 2 小時 15 分 |
| 鉅亨網 台股新聞 | `media`／`domestic` | [`news.cnyes.com/rss/v1/news/category/tw_stock`](https://news.cnyes.com/rss/v1/news/category/tw_stock) | 無 RSS 專屬條款；robots.txt 未禁止此路徑 | 標題、description、pubDate、guid（單篇 URL）、單篇連結；`content:encoded` 正文節錄不保存 | 每 2 小時；feed 約 65 則 | 未宣告 ttl；最多約排程間隔 2 小時 |
| 工商時報 證券 | `media`／`domestic` | [`www.ctee.com.tw/rss_web/livenews/stock`](https://www.ctee.com.tw/rss_web/livenews/stock) | 無 RSS 專屬條款；robots.txt 對一般 user-agent 無限制 | 標題、description、pubDate（無時區，依 +08:00）、guid、單篇連結 | 每 2 小時；feed 約 15 則 | ttl 60 分＋排程間隔，最多約 3 小時 |
| Yahoo奇摩股市 台股盤勢 | `media`／`domestic` | [`tw.stock.yahoo.com/rss?category=tw-market`](https://tw.stock.yahoo.com/rss?category=tw-market) | [RSS 說明](https://tw.stock.yahoo.com/rss-help)：個人與非營利、非商業用途，標示「Yahoo股市」，標題中的來源不得修改 | 標題、description、pubDate、單篇連結（guid 為空，以 canonical URL 識別） | 每 2 小時；feed 約 50 則 | ttl 5 分＋排程間隔，最多約 2 小時 5 分 |
| CNBC Top News、Market Insider、Technology | `media`／`international` | `www.cnbc.com/id/{100003114,20409666,19854910}/device/rss/rss.html` | 列於 [CNBC RSS 頁](https://www.cnbc.com/rss-feeds/) 供公開訂閱 | 標題、description、pubDate、guid（數字 ID，三個 feed 共用）、單篇連結；sponsored 項不收 | 每 2 小時；各約 30 則 | ttl 60 分＋排程間隔，最多約 3 小時 |
| MarketWatch Top Stories | `media`／`international` | [`feeds.content.dowjones.io/public/rss/mw_topstories`](https://feeds.content.dowjones.io/public/rss/mw_topstories) | Dow Jones 服務條款：個人、非商業用途 | 標題、description、pubDate、guid、單篇連結（去除 `mod` 參數） | 每 2 小時；feed 約 10 則 | ttl 60 分＋排程間隔，最多約 3 小時 |
| Federal Reserve 新聞稿 | `macro_official`／`international` | [`www.federalreserve.gov/feeds/press_all.xml`](https://www.federalreserve.gov/feeds/press_all.xml) | [公有領域](https://www.federalreserve.gov/disclaimer.htm)，需標示來源 | 標題、description、pubDate、guid（單篇 URL）、單篇連結 | 每 2 小時；feed 約 20 則 | 未宣告 ttl；最多約排程間隔 2 小時 |

延遲指來源發布到本系統可收錄的上限：feed 宣告的 ttl 加上排程間隔，不含來源自身發布到 feed 的時間。

未啟用：經濟日報 RSS（[robots.txt](https://money.udn.com/robots.txt) 禁止用於 LLM／AI 與商業用途，和新聞的 LLM 摘要衝突）；Yahoo Finance（沒有總表 feed，個股 headline feed 主機 robots.txt 全站禁止）；MarketWatch Market Pulse（2025 年後停更）；Reuters（無公開 RSS）。

- **請求**：固定 User-Agent `stock-lab-news/0.1 (+https://github.com/YiCheng0608/stock-lab)`，請求間隔 2 秒，逾時 20 秒，不重試；每次執行共 9 個請求。回應以串流讀取，超過 2 MB 即視為失敗；轉址只跟隨同一登錄主機，最多 5 次。
- **raw**：每個 feed 回應以 `persist_raw_payload` 存成 `news_<來源>`，內容為 HTTP 狀態、content type 與 feed 本文；寫入前移除 `content:encoded`，移除筆數記在 `removed_elements`。`naive_time_offset` 記錄無時區時間採用的時差（工商時報為 `+08:00`，其他為 null），同一值也寫在該來源 run 的 `metadata_json`。含 DOCTYPE 或實體宣告的文件一律視為格式錯誤。
- **文字**：標題與描述先解 HTML 實體再移除標籤，只合併半形空白；標題截到 300 字、guid 截到 180 字，超過 800 字的連結不收。
- **時間**：`pubDate` 依其時區轉 UTC，寫 `published_at`（精度 datetime）；沒有時間部分的值（`2026-10-17`、`20261017`）寫 `event_date`（精度 date），不補時分。工商時報的無時區 ISO 時間依 +08:00 解讀；其他來源的無時區時間、RFC 2822 的 `-0000`、不存在的日期都當作未知。來源時間晚於收錄時間 15 分鐘以上時，該則標 `time_consistency=conflict` 並隔離。
- **非股市內容**：中央社產經證券 feed 會混入生活（含彩券開獎）、社會等分類的稿件，CNBC Top News 會混入 CNBC Make It 專欄；這些稿件與標題含彩券、社會案件關鍵字者存為 `status=excluded`，不顯示、不送 LLM，raw 照存。各來源的排除分類與關鍵字見 [NEWS_SPEC §3](NEWS_SPEC.md#3-去重新資訊與事件影響)。
- **限制**：feed 只保留最近 10～65 則，抓取間隔內若超過這個數量會漏稿，漏掉的舊稿不回補。feed 的 `pubDate` 是來源宣稱的發布時間，不是本系統可證明的第一次可得時間。

## 欄位規則

### 法人口徑

日常 UI 將官方「外資及陸資」合計欄位簡稱為「外資」，raw、來源與稽核層保留正式統計口徑。「三大法人」只指外資、投信與自營商，不能把廣義券商或分點另併為法人類別。

### 成交金額可得狀態

`turnover` 數值欄在來源成交金額缺失或無效時存 `0`，另以 `turnover_status`／`turnover_reason` 保存欄位狀態；consumer 必須讀 status，不能憑數值 `0` 判定來源為零。

| 路徑 | 規則 |
| --- | --- |
| TWSE／TPEx 日行情 | [`parse_twse_daily_rows`／`parse_tpex_daily_rows`](../backend/worker/sources.py) 分別讀 `TradeValue`／`TransactionAmount`：缺失為 `0/unavailable/missing`，無效為 `0/unavailable/invalid`；明確、可解析的非負數（含合法 `0`）為 `available`、reason 為 null。成交額缺失不拒收該筆 bar。 |
| TAIEX | 指數 parser 合成的 `turnover=0` 標 `unavailable/synthetic_index`。 |
| 保存 | [`MarketBar`](../backend/app/models.py) 無來源證據時預設 `unknown`；[`_upsert_official_bar`](../backend/worker/pipeline.py) 保存數值、status 與 reason。`unknown` 的 reason 值域另有 `legacy_zero_ambiguous`（數值 0 但無法判定來源為零）與 `legacy_invalid`（負值或 NULL）。 |
| API 與計算 | [`bar_dict`](../backend/app/api.py) 輸出 `turnover_status`（`available`／`unavailable`／`unknown`）與 nullable `turnover_reason`。hot-group 與策略的法人 flow ratio 讀 `MarketBar.volume`（股），只在所需各日成交量皆為有限正值時使用，否則為 unavailable。 |

UI 空白與合法零的顯示規則見 [UI 文案規格](UI_COPY_SPEC.md)。

### 日行情成交量整數規則

成交量以**股**為單位，直接從原值型別判讀，不先轉浮點；有效輸出為 Python `int`，範圍 0～9,223,372,036,854,775,807。缺失或無效成交量拒收該筆 bar，不補零或截整；合法來源零保留。

| 原值或欄位條件 | 規則 |
| --- | --- |
| 別名順序 | TWSE 依 `TradeVolume`→`成交股數`→`成交量`；TPEx 依 `TradingShares`→`成交股數`→`成交量`。只有 `None` 或空白字串改讀下一欄；第一個非空值決定結果，無效主欄不以其他別名補值。 |
| 整數及 Decimal | 接受非 bool 的 `int`，或有限、非負、數學值為整數且未超上限的 `Decimal`。 |
| 字串 | 去除前後空白後須完整匹配 ASCII 十進位數字；可含開頭 `+`、前導零、正確千分逗號，以及小數點後全為零的小數部分，例如 `+1,234.000` 為 1234。 |
| 拒收 | 所有 float（含 `1234.0`）、bool、容器及其他型別；負值、非整數、NaN／Infinity、超上限；字串科學記號、負號、夾字、錯誤分組或內部空白。`1.9`、`12xyz`、`12,34` 都拒收。 |
| TPEx 空結果 | 回報日期檢查通過後，只有沒有表格列的 payload 可列入 `no_data_dates`。 |

### TAIEX 交易日基準

[`verified_taiex_sessions`](../backend/app/coverage.py) 與 backfill 日期報表的 `taiex_rows` 只計 `exchange=TWSE` 的 TAIEX／TWII index bar；TPEx 同名 index 不增加交易日分母、`taiex_rows` 或普通股票有效 bar 日。交易日校驗要求 active index、日期範圍與 provenance，並可回退到來源與日期相符的 raw `MI_INDEX`。TWSE 基準是兩市場普通股票共用的日期基準，沒有兩市場各自的交易日曆；session 列數不代表欄位可用。

### TPEx 停復牌規則

- `tpex_spendi_today` 的 `Date`、`SecuritiesCompanyCode`、`CompanyName`、`暫停交易`、`恢復交易` 同時容納暫停與恢復公告；collector 保存 raw，非空公告只記一則純文字 notice（collect 結果與 run metadata 的 `notices`），不改 bar 的停牌狀態，也不使 collect 變 `partial`；today／history 取得失敗記非核心 warning（[核心與非核心來源](#核心與非核心來源)），同樣不使 collect 變 `partial`。空列也不證明開市。
- 時間角色分開：row `Date` 是來源資料日；`DateOfSuspendedTrading`／`DateOfResumedTrading` 是事件生效日；collector 的 `data_as_of` 是研究截止；raw `collected_at` 是本系統取得時間。它們都不是官方發布時間。
- `parse_tpex_suspension_history_rows` 的代號欄順序為 `SecuritiesCompanyCode`→`Code`→`證券代號`→`代號`，取第一個非空值後須在 allowlist 內，不改讀其他欄；`Serial` 是編號，不能當代號。
- 同一代號恰有兩列、一列只有可解析的暫停日、另一列只有可解析的恢復日且暫停早於恢復時，合併為一個區間（`resumed_date`、`interval_end`、`resumption_source_row`）；其他形狀逐列處理，`interval_end=null` 的區間會向後無界延長。

### 公司行動欄位

TPEx：

- `stock_dividend_ratio`：只取 `StockDivdendThousandShares` 或 `每仟股無償配股` 第一個非空值，解析後除以 1,000；不得用 `StockDividend`、`權值`、`無償配股率`。
- `reference_price`：只讀 `ClosePriceBeforeExRightsDiviend` 或 `除權息前收盤價`；不得用 `OpeningReferencePrice`／`開始交易基準價`。
- `cash_dividend` 順序：`CashDivdend`→`CashDividend`→`現金股利`→`息值`；只在缺值或空白時看下一欄，第一個非空值只解析一次，非法值不降級。
- 調整因子為 `1/(1+Rf) × (P-C)/P`；沒有可信的現金增資比率與認購價，現金增資不支援。

TWSE：`GET /instruments/{symbol}` 的 `corporate_actions[]` 帶唯讀分類 `source_action_classification`：

| 欄位 | 規則 |
| --- | --- |
| `kind`／`label` | `ex_dividend`／`除息`、`ex_right`／`除權`、`ex_right_and_dividend`／`除權息`、`unknown`／`未知`。 |
| `raw` | `{"field":"Exdividend","value":...}`；原值為字串才保留，否則 null。 |
| `reason` | 依序 `unsupported_source`→`invalid_details`→`missing_official_field`→`alias_conflict`→`identity_mismatch`→`unknown_raw_value`→`trusted_twse_exact_fields`。 |

只有 action source 為 `twse`、標的交易所為 `TWSE`，且 `Code`／`Date`／`Exdividend` 都是非空字串時才分類：`Code` 等於代號、`Date` 是有效 7 碼民國日期且等於除權息日、`Exdividend` 只接受 `息`／`權`／`權息`。別名 `股票代號`／`證券代號`／`除權息日期`／`除權息` 只用於一致性檢查，不補缺值。分類不改 DB、調整因子或 raw。

## FinMind 補缺口規則

- FinMind（`https://api.finmindtrade.com/api/v4/data`）只用免費方案補官方來源沒有的歷史與缺日；目前 collector 未接 FinMind。
- 用途限本機個人非商用盤後研究；署名，不鏡像、不再散布 raw。
- FinMind 回 401／402／403 或要求付費、登入即停止，不在同一次取得內重試。
- FinMind 是服務提供者，不是官方直接來源：每筆保存來源 `finmind`、資料集名稱與擷取時間；不覆寫已存在的官方值，同一欄位不混用兩個來源；單位與 scale 依資料集文件判讀並在該資料集規則中寫明。
- 付費資料集不使用。
