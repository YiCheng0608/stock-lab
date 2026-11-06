<!-- owns: 來源選用原則、資料庫政策、官方來源、標的狀態同步、官方來源限制、新聞來源清單、法人口徑、籌碼來源欄位、融資標的清單、成交金額可得狀態、成交量整數規則、TAIEX 交易日基準、回補目標與確定休市日、大盤概況欄位、大盤概況 API 契約、交易日曆、TPEx 停復牌規則、公司行動欄位、FinMind 補缺口規則 -->
# 資料來源與限制

本文記錄資料來源、保存規則與已知限制；能力狀態以 [CAPABILITIES](CAPABILITIES.md) 為準。

## 來源選用原則

專案只用免費公開資料。依 [ROADMAP V1 基線](ROADMAP.md#v1-範圍基線2026-10-17-核定)，每日全市場行情、法人、融資與官方事件以官方 TWSE／TPEx 整批下載為主要來源；FinMind 免費方案補歷史回補與缺口（規則見[下節](#finmind-補缺口規則)），官方與 FinMind 都沒有的資料集才另提來源；新聞用免費公開的國內外媒體與官方來源，依 [NEWS_SPEC](NEWS_SPEC.md) 分開保存來源、時間與推論。新增來源前先在 Issue 記錄端點、欄位、授權、用途與限制。

## 資料庫政策

`collect`／`daily`／`backfill` 使用官方來源，SQLite 保存正規化市場資料、衍生研究資料與 raw 參照；缺資料的顯示依 [ROADMAP 顯示原則](ROADMAP.md#v1-範圍基線2026-10-17-核定)。新增媒體、國際或其他來源時，必須分開保存來源、版本、時間與推論，不能覆寫官方事實。DB 路徑、migration 與 readiness 見[環境、啟停與資料庫](ops/SETUP.md)。

## 官方來源

端點常數定義在 [`backend/worker/sources.py`](../backend/worker/sources.py)；下表只列 collector 實際呼叫的端點。

| 資料域 | 端點 | 用途與處理 | 限制 |
| --- | --- | --- | --- |
| TWSE universe | [上市公司 `t187ap03_L`](https://openapi.twse.com.tw/v1/opendata/t187ap03_L)、[ETF `t187ap47_L`](https://openapi.twse.com.tw/v1/opendata/t187ap47_L)、[新上市 `company/newlisting`](https://openapi.twse.com.tw/v1/company/newlisting) | 建立上市普通股與 ETF allowlist；數字代號 ETF 以 `t187ap47_L` 辨識。`company/newlisting` 列出 2011 年起所有上市案，只把 60 天內生效、主檔還沒有的列當新上市（`ipo`）。 | 名單是取得當下狀態，不含歷史上下市版本；用法見[標的狀態同步](#標的狀態同步)。 |
| TPEx universe | [issuer master `mopsfin_t187ap03_O`](https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O)、[ETF allowlist `etfFilter`](https://info.tpex.org.tw/api/etfFilter)（POST） | 建立上櫃普通股與 ETF allowlist。 | 混合行情中的權證、CB、ETN、興櫃不當成股票；興櫃 feed 不用來建 universe。 |
| TPEx 興櫃名冊 | [`mopsfin_t187ap03_R`](https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_R)（興櫃公司基本資料） | 當日 collect 1 個請求，只存代號、簡稱、市場別與資料日期，替新聞 AI 候選標名稱（[興櫃名冊](#興櫃名冊)，#512）。 | 非核心；不建 universe，不進行情、候選、族群或策略。 |
| TWSE 日行情 | 當日 [`STOCK_DAY_ALL`](https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL)；歷史 [`MI_INDEX`](https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX)（單日全市場表） | 保留 allowlist、普通股與 ETF 代號（[標的狀態同步](#標的狀態同步)），讀 OHLC、`TradeVolume`（股）、`TradeValue`。歷史以逐日全市場表回補，不逐檔逐月請求。同一份 `MI_INDEX`（`type=ALLBUT0999`，當日 collect 也會抓）另讀大盤統計資訊與漲跌證券數，寫[大盤概況](#大盤概況)；成交金額取「總計(1~15)」（含 ETF、權證等全部證券）。 | 明確 no-data 且無列可略過；錯日、缺日或日期不可驗的 payload fail-closed，不映射到其他交易日。 |
| TWSE 交易日曆 | OpenAPI [`holidaySchedule`](https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule)；網站版逐年 [`holidaySchedule?date=YYYY0101`](https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?date=20260101&response=json) | OpenAPI 版：多日回補時作正面排除清單，明列休市日不送 `MI_INDEX`。網站版：daily 的 trading_calendar 步驟存成 `trading_calendar_days`，推算訊號的規則最早執行日（見[交易日曆](#交易日曆)）。兩者的休市判定是同一個分類規則。 | 取得失敗不推論休市，回補該日照常請求並 fail-closed；只描述年度最新版本，不是歷史版本；颱風等臨時休市不會列入。 |
| TAIEX | 當日 [`exchangeReport/MI_INDEX`](https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX)；歷史取自 `MI_INDEX` 全市場表 | 加權指數作 hot-group 超額報酬基準與交易日基準（見 [TAIEX 交易日基準](#taiex-交易日基準)）。 | 只有收盤值；合成的 O／H／L、成交量與成交額不是真實欄位。 |
| TPEx 大盤概況 | [`tpex_mainborad_highlight`](https://www.tpex.org.tw/openapi/v1/tpex_mainborad_highlight)（上櫃股票市場現況；官方路徑拼作 `mainborad`） | 當日 collect 每天 1 個請求，寫[大盤概況](#大盤概況)：`CloseIndex`、`IndexChange`、`DailyTradingValue`（**百萬元**，×1,000,000 存成元，只算上櫃股票）與 `PriceRise`／`PriceDecline`／`PriceFlat`／`LimitUp`／`LimitDown` 各 `…CompanyNumbers`、`UnmatchedCompanyNumbersSuspensionStocksIncluded`；`DailyTradingVolume`（**千股**）、`ListedCompanyNumbers`、`MarketCapitalization` 等不保存。 | 只有最新一天，沒有歷史：`Date` 是民國日期（`1151022`），不等於請求的交易日（例如還沒更新）時不寫並記 warning，不映射到其他日期；漏抓的日子不回補，那天沒有上櫃列。 |
| TPEx 日行情 | [`dailyQuotes`](https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes)（POST） | 逐日擷取，保留股票／ETF allowlist、普通股與 ETF 代號（[標的狀態同步](#標的狀態同步)），讀 OHLC、`TradingShares`（股）、`TransactionAmount`。 | 回報日期須等於請求日期；非空但全部被拒收的表格不算合法空日。 |
| TWSE 籌碼 | 法人 [`T86`](https://www.twse.com.tw/rwd/zh/fund/T86)；融資 [`MI_MARGN`](https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN) | 法人依外資及陸資、投信、自營商分類；融資讀餘額與增減。 | 請求可能被限流、重導或缺可驗證日期。 |
| TPEx 籌碼 | 法人 [`insti/dailyTrade`](https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade)；融資 [`margin/balance`](https://www.tpex.org.tw/www/zh-tw/margin/balance) | 同 TWSE 口徑；[三大法人買賣明細](https://www.tpex.org.tw/zh-tw/mainboard/trading/major-institutional/detail/day.html)明列外資及陸資、投信、自營商及合計。 | 缺資料時不補 0；官方檔未列的語意見[法人口徑](#法人口徑)。 |
| 公司行動 | daily：TWSE [`TWT48U_ALL`](https://openapi.twse.com.tw/v1/exchangeReport/TWT48U_ALL)；TPEx [`tpex_exright_daily`](https://www.tpex.org.tw/openapi/v1/tpex_exright_daily)。回補：TWSE `TWT49U`＋`TWT49UDetail`、TPEx `exDailyQ`（除權除息計算結果表，見[除權息回補](#除權息回補)） | 除權息資料寫入 corporate actions，作價格調整與追蹤比較。 | daily 兩個來源只有當天的事件（`TWT48U_ALL` 另有未來預告，不寫入），沒收到的那天由回補補上。欄位規則見[公司行動欄位](#公司行動欄位)。 |
| 停復牌 | TPEx [`tpex_spendi_today`](https://www.tpex.org.tw/openapi/v1/tpex_spendi_today)、[`tpex_spendi_history`](https://www.tpex.org.tw/openapi/v1/tpex_spendi_history) | history 轉為可稽核的停牌區間事件；區間內缺 bar 視為不可比。 | today 同時列暫停與恢復公告，代號存在不等於仍停牌；TWSE 停牌歷史未接入，追蹤可能為不可比。見[停復牌規則](#tpex-停復牌規則)。 |
| 重大訊息（依日期） | MOPS [`t05st02`](https://mops.twse.com.tw/mops/#/web/t05st02)（`POST https://mops.twse.com.tw/mops/api/t05st02`，JSON 民國年／月／日） | 事件覆蓋的唯一證據：每個查詢日記已核實、已核實空日或 partial；上市、上櫃重大訊息寫入 events。 | 清單只有主旨，沒有說明全文。規則見[重大訊息日期查詢](#重大訊息日期查詢)。 |
| 重大訊息／基本面 | TWSE [`t187ap04_L`](https://openapi.twse.com.tw/v1/opendata/t187ap04_L)、[`t187ap14_L`](https://openapi.twse.com.tw/v1/opendata/t187ap14_L)；TPEx [`mopsfin_t187ap04_O`](https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O)、[`mopsfin_t187ap14_O`](https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap14_O) | 官方事件與基本面 snapshot。基本面的「出表日期」寫成可得日，同一季只保留第一次看到的最早日期，之後重新出表不覆寫（[季度財報回補](#季度財報回補)）。 | 只是取得當下的 snapshot，不能重建歷史可得時間；基本面不是 v1 策略輸入。同股同日多則不同公告標題相同時，以發言時間區分：最早一則保留原標題，之後各則標題加「（發言時間 HH:MM:SS）」（內容完全相同的重複列只留一則），之後重抓不會改名已存的事件。 |
| 季度財報（回補） | MOPS 彙總報表－綜合損益表 [`t163sb04`](https://mops.twse.com.tw/mops/#/web/t163sb04)（舊站 `POST https://mopsov.twse.com.tw/mops/web/ajax_t163sb04`，HTML） | 手動的 `fundamentals backfill` 回補近 8 季的累計營收與基本 EPS，寫入 `fundamental_snapshots`（`source=mops_t163sb04`）；daily 在申報期限前後的窗口自動補最近 2 季。上市、上櫃每季各 1 個請求。 | 沒有實際公告日，可得日用法定申報期限；不屬於 collect。規則見[季度財報回補](#季度財報回補)。 |
| 月營收（快照） | TWSE [`t187ap05_L`](https://openapi.twse.com.tw/v1/opendata/t187ap05_L)、TPEx [`mopsfin_t187ap05_O`](https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O)（每月營業收入彙總表） | 當日 collect 各 1 個請求，寫入 `monthly_revenues`（`source=mops_t187ap05`）：當月營收、去年當月營收、去年同月增減(%)、當月累計營收（千元），可得日用出表日期（[月營收](#月營收)，#530）。 | 非核心；只有最新一個月，整份共用一個出表日期，不是各公司的申報日。 |
| 月營收（回補） | MOPS 營業收入統計表 `t21sc03` 靜態頁（`GET https://mopsov.twse.com.tw/nas/t21/<sii\|otc>/t21sc03_<民國年>_<月>_<0\|1>.html`，Big5 HTML） | 手動的 `revenue backfill` 回補近 24 個月，寫入 `monthly_revenues`（`source=mops_t21sc03`）；daily 在每月 1～20 日自動補最近 2 個月。每個市場月 2 頁：`_0` 國內公司、`_1` 國外公司（`-KY`、`-DR`）。 | 沒有實際申報日，可得日用法定期限次月 10 日；不屬於 collect。規則見[月營收](#月營收)。 |

每筆 raw 保存 endpoint、SHA-256、擷取時間與 data-as-of；正規化資料可回指 raw payload；重抓時日線與籌碼列指向哪一次 capture、哪些值會改，見 [重跑與回補的冪等](ops/SCHEDULING.md#重跑與回補)。News／Event 有官方事件投影、來源連結、raw 稽核與時間欄位，但欄位存在不代表每筆來源時間可信，詳見 [NEWS_SPEC](NEWS_SPEC.md)。`ChipSnapshot` 雖定義當沖、融券與借券欄位，現有寫入路徑不收集這些值。券商分點列後版，collector 不接入。

### 核心與非核心來源

collect 的狀態只看核心來源：日行情（`STOCK_DAY_ALL`、`MI_INDEX`、`dailyQuotes`）、TAIEX、交易日曆、法人與融資。它們的 warning 讓 collect 變 `partial`，daily 不跑 analyze。重大訊息與基本面（`t187ap04_L`、`t187ap14_L`、`mopsfin_t187ap04_O`、`mopsfin_t187ap14_O`、MOPS `t05st02`）、TPEx 停復牌（`tpex_spendi_today`、`tpex_spendi_history`）、[興櫃名冊](#興櫃名冊)（`mopsfin_t187ap03_R`）、[月營收](#月營收)快照（`t187ap05_L`、`mopsfin_t187ap05_O`）及[大盤概況](#大盤概況)（TWSE `MI_INDEX` 的大盤統計與漲跌證券數、TPEx `tpex_mainborad_highlight`；`MI_INDEX` 的日行情與 TAIEX 仍是核心）是非核心：取得失敗記為 `noncore_warnings`，collect 仍為 `success`；被防呆略過的[標的狀態同步](#標的狀態同步)也記為 `noncore_warnings`。缺的事件與基本面照「缺資料留空」處理（`mops_events`／`mops_fundamentals` 的資料品質列為 `partial`）。分類依 warning 文字（`pipeline.NONCORE_WARNING_PATTERN`），新增來源的 warning 未列入前一律算核心。

### 標的狀態同步

官方清單只描述取得當下有哪些標的（上表的 TWSE、TPEx universe），行情表則會留著已離開清單的公司列。規則如下（[#212](https://github.com/YiCheng0608/stock-lab/issues/212)）：

- **行情與籌碼不以當天清單過濾普通股與 ETF**：
  - 4 位數、非 0 開頭、非 91 開頭的代號（普通股），以及 `00` 開頭、4～6 碼、最後可帶一個大寫字母的代號（ETF，例如 `0050`、`006208`、`00679B`）一律保留；特別股（帶字母）、權證、可轉債、ETN、存託憑證（91 開頭或 6 位數）仍只收 allowlist 內的。
  - ETF 也要保留，是因為清盤中的 ETF 會在最後交易日前就離開 ETF 清單：TPEx 債券 ETF 00793B、00847B 在 9/09 的 `etfFilter` 還在、10/17 已不在，行情卻到 9/17、10/02 才停；舊規則讓 10/17 的回補把它們之後的行情列全部丟掉（#393）。
  - collect 把這些列寫入 DB 中同交易所、同代號的既有標的；DB 沒有的記為 `unmatched_bar`，不建標的、不丟棄；之後標的建立了，collect 以已存的 raw 補寫這些日線（#388；規則見 [重跑與回補](ops/SCHEDULING.md#重跑與回補)）。
- **狀態**：只有抓當日快照的 collect 會同步，歷史回補與 catchup 不做。
  - 現行的股票、`ipo` 或 ETF 若不在所屬交易所當天的清單：另一交易所清單有同代號時標 `transferred`，否則標 `delisted`。
  - 例外：不在清單、但所屬交易所最新一個 TAIEX 交易日的已存行情表（TPEx `dailyQuotes`、TWSE `MI_INDEX`）還有該代號這一列（無成交的 `--` 列也算）的，表示仍在交易，維持原狀態，代號列在 `instrument_status_sync` 的 `quoted_absent_symbols`；之後行情表不再有它才依清單判定（#393）。最新交易日沒有已存、日期核對過的行情表時無法確認，照清單判定，`quote_check` 記 `unverifiable`。
  - 該標的未關的成員列（產業、ETF、題材）一律關閉，不刪列：轉市關到新市場上市日前一天，下市關到清單觀測日前一天，都不早於該列的 `valid_from`。
  - 每次變更寫一列 `data_quality`（`entity_type=instrument_status`），記前後狀態、原因、關閉的成員列與清單 capture 的 endpoint、SHA-256、raw id。
  - **休眠（推定）**：仍在清單內、但最近 60 個交易日的已存行情表（TPEx `dailyQuotes`、TWSE `MI_INDEX`）完全沒有該代號這一列的現行標的，標 `dormant`。無成交的 `--` 列也算有列，所以停牌一兩個月的正常股票不會被關。
    - 要先有 60 個 TAIEX 交易日，且每一天都有已存、日期核對過的行情表才判定，否則該次不判定。
    - 證據寫在 `instrument_status` 列的 `presumption`：推定敘述、檢查的交易日區間、60 個 raw id 與最後日線日，和依清單判定的 `delisted`／`transferred` 分開。
    - 清單更新不會讓 `dormant` 回到 `active`，只有行情列重新出現才會：下一次同步看到最新行情表又有這一列，或 collect 寫入它晚於休眠判定日（沒有判定紀錄時為最後一根日線）的日線。回補休眠以前的舊日期只補日線，不改狀態。休眠中不投影產業與 ETF 成員列。
  - 標的重新出現在清單時，`delisted`／`transferred` 改回 `active`。
  - `delisted`／`transferred`／`dormant` 標的保留歷史，個股頁仍可查；但不進 `/api/stocks` 清單、首頁標的數、族群成員數與分數、訊號與候選池。
- **防呆**：某交易所一次要改（`delisted`、`transferred`、`dormant` 合計）的標的超過現行標的的 5%（至少 5 檔）時，該交易所整批不改，記 `noncore_warnings` 與 `instrument_status_sync` 為 `skipped`，由看門狗留言（[排程看門狗](ops/WATCHDOG.md)）。
- **轉上市**：
  - `company/newlisting` 的 `Note` 欄寫「櫃轉市」（例如 8908 欣雄 `ApprovedListingDate 1151016`）。新市場的標的在 60 天內和新上市一樣標 `ipo`，舊市場的標的標 `transferred`，兩邊的歷史目前分開存。
  - 之後要合併前後歷史時，以 `Note=櫃轉市`、舊標的 `transferred` 狀態，以及 `instrument_status` 列記的新市場上市日，把同代號的兩個標的接起來。合併延後到 G7 之後（[#1](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-6385195520)）。
- **限制**：沒有接終止上市或停牌公告。仍在清單內、停止買賣未滿 60 個交易日的股票維持 `active`；日線停在最後交易日，`/stocks` 列表在最近收盤下方標出它的日期。

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

**官方檔未列**：T86（`selectType=ALL`）與 TPEx `insti/dailyTrade` 是逐證券的買進／賣出／買賣超明細，只列當天有法人成交的證券。T86 `notes` 寫明「含一般、零股、盤後定價、鉅額，不含拍賣、標購」。籌碼列照原樣保存：不在法人檔的股票，籌碼列只有融資值（來源 `twse_margin`／`tpex_margin`，三大法人欄 null），或者沒有籌碼列。只有 [`hot_group_v1`](spec/hot_group.md) 1.1.0 在證據成立時把這種日子記為淨額 0。2026-09-08～10-16 的 52 份官方檔（[#208 核對](https://github.com/YiCheng0608/stock-lab/issues/208#issuecomment-6247696969)）核對結果如下：
- 每份都是 stat OK、日期相符，宣告筆數等於實際列數。
- 買進、賣出欄全為 0 的列有 0 筆；淨額為 0 但有成交的列照樣列出。
- 來源含 `t86`／`3insti` 的籌碼列全部指向當日官方法人端點的 raw，而且沒有任何一列的三大法人欄是 null。

策略與候選的法人輸入仍把缺列視為缺資料；個股頁把這種日子寫成「官方三大法人表未列此股」（`institutional_not_listed`，[UI_COPY_SPEC §6.1](UI_COPY_SPEC.md#61-資料不足的原因句)），不寫成待補。

### 籌碼來源

一筆籌碼列的值來自兩份官方檔：三大法人（`foreign_buy`、`trust_buy`、`dealer_buy`，上市 T86、上櫃 `insti/dailyTrade`）與融資（`margin_balance`、`margin_change`，上市 `MI_MARGN`、上櫃 `margin/balance`）。兩份檔公布時間不同（2026-10-19 起 18:30 的 collect 只拿得到法人檔，融資由 21:30 補上），所以每組值各記自己的來源（[#395](https://github.com/YiCheng0608/stock-lab/issues/395)，migration 0021）：

| 欄位 | 法人 | 融資 |
| --- | --- | --- |
| 來源 | `institutional_source`（`twse_t86`／`tpex_3insti`） | `margin_source`（`twse_margin`／`tpex_margin`） |
| raw 參照 | `institutional_raw_payload_id` | `margin_raw_payload_id` |
| 資料日 | `institutional_data_as_of` | `margin_data_as_of` |
| 收集時間 | `institutional_collected_at` | `margin_collected_at` |

- 收集時間是這一組目前的來源寫進這列的本機時間：新列、列原本沒有這一組、法人更正、`force` 時取寫入當下；只補空欄不改。0021 以前的列由 `chips provenance` 回填時，列已有的組沿用列層級 `collected_at`（舊程式寫入時記的就是它）；列原本沒有、回填才建立的組（2026-10-19 起 21:30 補上融資的列的融資組）沒有記寫入時間，以那份融資 capture 的擷取時間代替（寫入發生在同一次 collect 的擷取之後），但不早於列層級原值。所以回填只會讓列層級 `collected_at` 不變或變晚。
- 該列沒有那份檔時，那一組四欄都是 null，值也是 null（只有融資、只有法人的列照樣保存，見[法人口徑](#法人口徑)）。
- 列層級的 `source`、`raw_payload_id`、`data_as_of`、`collected_at` 是兩組的摘要（`app.chip_provenance.summarize`）：`source` 依法人、融資的順序以 `+` 連接兩組來源；`raw_payload_id` 與 `data_as_of` 取法人組，沒有法人組時取融資組；`collected_at` 取兩組中較晚的。
- 寫入規則見 [重跑與回補](ops/SCHEDULING.md#重跑與回補)；0021 以前寫入的列由 [`chips provenance`](ops/CLI.md#現有-worker-cli) 依已存的 raw 補寫。補寫前，讀取端依列層級欄位推出兩組（`app.chip_provenance.legacy_groups`）；這時融資組沒有 raw 參照，10/19 起由 21:30 補上融資的列看不出融資來源。
- API `GET /api/stocks/<exchange>/<symbol>` 的 `chips[]` 帶 `institutional`、`margin`（各含 `source`、`data_as_of`、`collected_at`，沒有該組為 null）；個股頁「法人籌碼」的表格欄位依各自那一組判斷單位，來源說明分 `法人：`、`融資：` 兩行。

### 融資標的清單

官方融資融券餘額表列的是當日得信用交易的有價證券，所以它就是當日的融資標的清單（[#392](https://github.com/YiCheng0608/stock-lab/issues/392)）。上市用 `MI_MARGN`（`selectType=ALL`）的「融資融券彙總 (全部)」表，欄位取 `代號`、`註記`；上櫃用 `margin/balance` 的「上櫃股票融資融券餘額」表，欄位取 `代號`、`備註`，代號空白的合計列不算。不另抓 endpoint，collect 抓融資時就有。

- **保存**：`margin_lists` 每個交易所每日一列，記 `source`（`twse_margin`／`tpex_margin`）、`endpoint`、`data_as_of`、`raw_payload_id`、`collected_at`、`member_count` 與 `members_json`（代號→註記，去前後空白）。collect 寫入它剛存的融資表（`worker.margin_lists`，失敗只記在 run 的 `margin_lists`、不影響 collect）；歷史由 [`margin-lists`](ops/CLI.md#現有-worker-cli) 從已存 raw 回補。
- **選哪份 capture**：該日最新一份「回報日期相符、而且有證券列」的 capture。18:30 的融資表還沒有個股列，不算；回報日期不符（退回最新日）也不算。代號與註記都相同時不改寫。
- **取不到時**：沒有可用的 capture 就不寫列。這天的清單是未知，融資條件記缺資料，不推成不適用。raw 檔讀不到、不是 JSON 或 SHA-256 不符時，停在該日，回 `failed` 與 `failed_date`。
- **驟減防呆**：清單比該交易所前一個已存清單少超過 5%（`MAX_MEMBER_DROP`）時不寫，記 `suspicious_drop`，這天的融資條件也記缺資料。官方表被截斷時，漏掉的融資標的會被判成不適用、略過融資確認，判定會往放寬的方向錯。2024-09-30～2026-10-30 的實際清單每日最多只少 0.24%。看門狗怎麼回報這種情況，由 [#390](https://github.com/YiCheng0608/stock-lab/issues/390) 處理。
- **註記不參與判定**：`O`（停止融資）、`X`（停止融券）、`!`（停止買賣）等符號描述的是次一營業日的狀況，而且停止融資期間的餘額仍會因償還而變動，所以只保存、不拿來判定。
- **策略怎麼用**：見 [breakout_v2](spec/breakout_pullback.md#breakout_v2pullback_v2)。
- **已知限制：轉市標的**：判定用標的目前的交易所（`instruments.exchange`）去查各日清單。窗口 6 天裡若有轉市前的日子，那幾天查的是另一個交易所的清單，可能把融資標的誤判成不適用。轉市很少，而且只影響轉市後 5 個交易日內的判定，目前不另外處理。

### 官方無成交日

冷門股與債券 ETF 當天沒有一般交易時段成交時，官方每日行情表仍列出這一檔，但開、高、低、收全部空白：上市 `MI_INDEX`（`type=ALLBUT0999`）的「每日收盤行情」表是 `--`，上櫃 `dailyQuotes` 的「上櫃股票行情」表是 `---`。成交股數可能是 0，也可能只有零股或盤後的股數（[#454](https://github.com/YiCheng0608/stock-lab/issues/454) AC-1：2026-10 的 201 檔未滿 20 日中，556 個缺日是這種列）。日行情 parser 不收這種列，所以它不是 bar；它是「這天官方確認沒有價格」的證據，不是缺資料，也不補價、不補零。

- **保存**：`no_trade_days` 每個標的每日一列，記 `source`（`twse`／`tpex`）、`endpoint`、`data_as_of`、`raw_payload_id`、`collected_at`。collect 寫入它剛存的行情表（`worker.no_trade_days`，失敗只記在 run 的 `no_trade_days`、不影響 collect）；歷史由 [`no-trade-days`](ops/CLI.md#現有-worker-cli) 從已存 raw 回補。
- **判定**：四個價格欄都存在且都空白（空字串或只有 `-`）才算；只缺部分價格的列是格式異常，仍算缺資料。上市取 `parse_twse_all_daily_payload` 用來產生 bar 的同一張表。
- **選哪份 capture**：該交易所該日最新一份「回報日期相符、而且有證券行情表」的 capture（有列但沒有行情表的 capture 跳過，不拿來清掉該日的列），並以它重建該日該交易所的所有列：之後的 capture 改成有價格，舊列就刪掉。休市日官方回「沒有符合條件的資料」或空表時記 `no_data`（不算缺）；沒有任何可用 capture 時記 `missing`。兩者都保留原有的列，coverage 照樣只看已存的列。raw 檔讀不到、不是 JSON 或 SHA-256 不符時，停在該日，回 `failed` 與 `failed_date`。
- **與 bar 的關係**：同一標的同一天已有 bar（例如當日快照有價格）時不寫，coverage 也以 bar 為準。代號在 `instruments` 找不到的股票或 ETF 列只計入 `unmatched`，不寫；同表的權證、債券等代號不計。
- **表上沒有這一列**：不算無成交，仍是缺資料。AC-1 的 88 個這種缺日集中在少數標的、連續數天，看起來是停止買賣，但目前沒有可對應的停牌來源，所以不推定。個股頁把它寫成「官方行情表未列此股」（`quote_not_listed`）：那天同交易所已有其他股票的 bar，所以不是收集缺口；整個交易所都沒有 bar 的日子才寫「行情尚未收錄」（`missing_bar_dates`，可回補）。2026-11-04 的副本上 32 檔有前者、0 檔有後者，前者多是減資換股期間連續 5～7 天（[#511](https://github.com/YiCheng0608/stock-lab/issues/511)）。
- **誰讀它**：coverage（`/api/coverage`、回補報表）計入涵蓋。個股頁與行動摘要的覆蓋原因也讀它（`official_no_trade`，[UI_COPY_SPEC §6.1](UI_COPY_SPEC.md#61-資料不足的原因句)），但只用來說明原因：指標、策略、追蹤與「20 日基準還缺幾日」照舊只看 bar，無成交日怎麼處理另議。

### 興櫃名冊

新聞 AI 候選標的常是準備上市櫃的興櫃公司，例如 7808 訊聯智藥、8058 耐特。這些公司不在 `instruments`，以前卡片只能寫「代號未對應到已知標的」。2026-10-29～11-05 正式 DB 的 news_v3 候選裡，對不到名稱的 10 個全是興櫃股（[#512](https://github.com/YiCheng0608/stock-lab/issues/512)）。所以另存 TPEx 的興櫃公司名冊，只拿來替候選標名稱。

- **來源**：TPEx OpenAPI [`mopsfin_t187ap03_R`](https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_R)（興櫃公司基本資料）。格式同上櫃的 `mopsfin_t187ap03_O`，讀 `SecuritiesCompanyCode`（代號）、`CompanyAbbreviation`（簡稱）與民國 `Date`（資料日期）。2026-11-05 那份有 367 家。
- **取得**：當日快照的 collect 每次 1 個請求，存 raw（endpoint、SHA-256、data-as-of）。raw 的 `data_as_of` 是名冊自己的 `Date`（資料日期，與 `emerging_issuers.as_of_date` 相同），不是 collect 日；各列 `Date` 不一致時為空，該份同時被拒收。歷史回補與 catchup 不抓：名冊只有當下的名單。名冊是當下清單、不是交易日報表，所以官方確認無資料的日子也照抓。
- **檢核**：每列的 `Date` 要相同，且不晚於 collect 日；代號不是 4～6 位數字或大寫字母、或沒有簡稱的列略過；同一代號出現兩次，或沒有任何可讀的列，整份拒收。
- **非核心**：取得或解析失敗、或寫入失敗，記 `noncore_warnings` 的 `TPEx emerging issuers unavailable: …`，不寫任何一列，collect 仍為 `success`；run metadata 的 `emerging_issuers` 記 `inserted`／`updated`／`unchanged`／`older` 的列數，失敗時記 `failed`。
- **保存**：`emerging_issuers`（0027）每個代號一列：`symbol`、`name`、`market`（固定 `emerging`）、`as_of_date`（名冊的資料日期）、`raw_payload_id`。新名冊會更新同代號的名稱、資料日期與 raw；資料日期較舊的名冊（重抓舊日）不改。後來不在名冊上的代號保留原列，資料日期停在舊的那天。
- **誰讀它**：只有新聞 API 替 AI 候選標名稱（[NEWS_SPEC §5](NEWS_SPEC.md#5-ai-摘要與推論)），而且只讀資料日期最新那份名冊上的代號，所以已經掛牌上市櫃、或已撤銷興櫃的公司，不會沿用舊名冊標成興櫃。它不是 `instruments`，不建 universe，也不進行情、指標、候選、族群、策略、`/api/stocks` 或規則關聯的名稱比對。沒有興櫃行情。

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

### 回補目標與確定休市日

回補 run 的 `target_met` 有三處：metadata 頂層、`coverage_manifest_summary`、`coverage`。這三處和 `/api/coverage` 的 `summary.target_met` 都用同一條規則（[#479](https://github.com/YiCheng0608/stock-lab/issues/479)）：

- **目標**：`min(65, 窗口平日數 − 確定休市日)`，已驗證交易日（[TAIEX 交易日基準](#taiex-交易日基準)）達到目標就算達成。
  - 回補 run 的窗口平日數含延伸補抓日；短範圍的上限是範圍內的平日數。
  - run metadata 記 `target_sessions` 與 `confirmed_non_trading_dates`。
  - `/api/coverage` 的 summary 記 `target_ohlcv_taiex_sessions`（扣除後）、`target_ohlcv_taiex_cap`（扣除前）與 `confirmed_non_trading_dates`。
  - `coverage_targets.ohlcv_taiex_sessions` 仍是上限 65；要不要延伸補抓照舊看它，窗口還有空間就往前補。
- **確定休市日**：要同時符合三個條件：
  - 那個週間日沒有成功、含 TAIEX 的 collect；
  - 有官方明確回 no-data 的 collect（status `skipped`）；
  - 這個 no-data 已經確認：回應是在該台北日結束後才取得的（之後的 catchup 或回補），或 daily 對該日記過 `non_trading_day`（23:00 再問一次仍是 no-data）。

  只有當天一次 no-data、沒有確認的日子仍算缺資料。這條規則也決定 catchup 要不要補抓（[重跑與回補](ops/SCHEDULING.md#重跑與回補)），只寫在 `app.coverage.collect_states` 一處。官方休市表（[交易日曆](#交易日曆)）不讀：颱風等臨時休市不在表上（2026-10-23），官方 no-data 兩種都涵蓋。
- **為什麼要扣**：延伸補抓不能早於迄日前 93 日。93 日的窗口約 66～67 個平日，扣掉休市日常湊不到 65 日。例如 run 2266（08/03～11/03）有 67 個平日、5 個確定休市日、驗證到 62 日：舊規則永遠「尚未達成」，新規則的目標是 62，已達成。
- **日期表**：有回補 manifest 或指定了起訖時，`/api/coverage` 把確定休市日列為 `skipped_non_trading`，計入 `skipped_non_trading_dates`；當天有 MOPS 事件列也一樣，不顯示成 `partial`。完全沒有回補 manifest 的快照模式不扣休市日，目標維持 65。

### 大盤概況

`market_summaries` 每個交易所每個交易日一列（unique `exchange + trading_date`），回指 raw（`raw_payload_id`），經 `GET /api/dashboard` 的 `market_overview` 提供（契約見 [大盤概況 API 契約](#大盤概況-api-契約)）；只用於顯示，不是策略或候選的輸入（[#275](https://github.com/YiCheng0608/stock-lab/issues/275)）。

| 欄位 | 上市（TWSE `MI_INDEX`） | 上櫃（TPEx `tpex_mainborad_highlight`） |
| --- | --- | --- |
| 指數 | 「價格指數(臺灣證券交易所)」的「發行量加權股價指數」列：`收盤指數`；漲跌點數是未帶正負號的 `漲跌點數` 加上 `漲跌(+/-)` 欄的 HTML 標記（`<p style ='color:green'>-</p>`）；漲跌幅是官方 `漲跌百分比(%)`，`change_pct_method=official`。標記為空且點數為 0 是平盤，`X` 或其他標記為 null；標記與百分比正負相反時兩者都存 null | `CloseIndex`、`IndexChange`（帶正負號）；官方沒有漲跌幅，以 `IndexChange ÷ (CloseIndex − IndexChange)`（前一日收市指數）計算，`change_pct_method=derived` |
| 成交金額（元，整數） | 「大盤統計資訊」的「總計(1~15)」，含 ETF、權證等全部證券，`turnover_scope=twse_all_securities`；即一般網站的大盤成交值，等於 OpenAPI `FMTQIK` 的 `TradeValue`（只算股票的「證券合計(1+6+14+15)」不用） | `DailyTradingValue` × 1,000,000，只算上櫃股票，`turnover_scope=tpex_stocks`（10/22 為 225,545 百萬元，等於已收 `dailyQuotes` 四碼普通股成交金額合計） |
| 漲跌家數 | 「漲跌證券數合計」的「股票」欄（不是「整體市場」）：`247(3)` 拆成上漲 247、漲停 3，跌停同理；持平、未成交、無比價（`not_comparable`）；`breadth_scope=twse_stocks` | 上漲、下跌、平盤、漲停、跌停、未成交（含暫停交易）；沒有無比價；`breadth_scope=tpex_stocks` |

- **選表**：依表名（去掉民國日期前綴）、列名與欄名找，不依表格順序或欄位位置；同名的表、列或欄出現兩次就不取。報酬指數表的同名列不用。
- **缺值**：缺表、缺列、缺欄或無法解析的值存 null，不補 0；三張表都沒有才整份拒收。整數只接受數字與正確的千分位。
- **日期**：`MI_INDEX` 的 `date` 與 highlight 的 `Date` 都必須等於請求的交易日，否則整份拒收，不映射到其他日期。
- **寫入**：上市列與 TAIEX bar 由同一次 collect、同一份 `MI_INDEX` raw 寫入（`raw_payload_id` 相同），不另發請求；歷史回補與 catchup 也寫上市列，highlight 只在抓當日快照的 collect 請求。重抓與日行情相同：值相同不改、只補空欄、不同值保留第一次寫入的值（`--force` 才改寫並改指向新的 raw）；寫入筆數記在 collect run 的 `market_summaries`。擷取、解析或寫入失敗記 `noncore_warnings`（`… market summary unavailable for <日期>: …`），collect 狀態與其他步驟不受影響。
- **回補**：`python -m worker.cli market-summary --from --to` 只讀已存的上市 `MI_INDEX` raw（[現有 worker CLI](ops/CLI.md#現有-worker-cli)）；上櫃沒有歷史，上線前的日期沒有上櫃列。

#### 大盤概況 API 契約

`GET /api/dashboard` 的 `market_overview` 只讀 `market_summaries`（來源與欄位規則見 [DATA_SOURCES](#大盤概況)），不新增 route：

```json
"market_overview": {
  "trading_date": "2026-10-22",
  "exchanges": [
    { "exchange": "TWSE", "status": "available",
      "index": { "name": "加權指數", "close": 46041.43, "change": -846.34, "change_pct": -0.0181, "change_pct_method": "official" },
      "turnover": { "value": 933437473560, "scope": "twse_all_securities", "scope_label": "集中市場總計（含 ETF、權證等）" },
      "breadth": { "advancers": 247, "decliners": 756, "unchanged": 74, "limit_up": 3, "limit_down": 5, "unmatched": 7, "not_comparable": 0, "scope": "twse_stocks" },
      "source": { "label": "臺灣證券交易所 MI_INDEX", "collected_at": "2026-10-22T10:30:05+00:00", "data_as_of": "2026-10-22", "raw_payload_id": 1 } },
    { "exchange": "TPEx", "status": "unavailable", "reason": "row_date_mismatch", "latest_trading_date": "2026-10-21" }
  ]
}
```

- `trading_date` 等於 `dashboard.as_of`；`exchanges` 固定是 TWSE、TPEx 兩項，各自判斷，一邊沒有不影響另一邊。
- 只顯示 `as_of` 當日的列，其他日期的列不代替。`unavailable` 的 `reason`：`no_verified_session`（`as_of` 為 null）、`row_date_mismatch`（該交易所最新一列不是 `as_of`，附 `latest_trading_date`）、`not_collected`（沒有任何列）。
- `change_pct` 是比例（−0.0181 即 −1.81%）；`change_pct_method` 為 `official`（TWSE 官方）或 `derived`（TPEx 依前一日收市指數計算）。`turnover.value` 單位元；`scope` 只有 `twse_all_securities`（`scope_label`「集中市場總計（含 ETF、權證等）」）與 `tpex_stocks`（「上櫃股票」）。上櫃沒有無比價，`not_comparable` 為 null。
- 缺值為 null（`status` 仍為 `available`），不補 0；`source.collected_at` 是該份 raw 的擷取時間（UTC）。

### 交易日曆

TWSE 的年度市場開休市日期，上市與上櫃共用（同 [TAIEX 交易日基準](#taiex-交易日基準)）。實作在 [`worker/trading_calendar.py`](../backend/worker/trading_calendar.py)（抓取與保存）與 [`app/trading_calendar.py`](../backend/app/trading_calendar.py)（分類與推算），[#294](https://github.com/YiCheng0608/stock-lab/issues/294)。

- **端點**：`https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?date=<西元年>0101&response=json`，和 `MI_INDEX`、OpenAPI 休市表同屬 TWSE 官方免費網站。回傳 `stat`、`queryYear`、`total`、`fields`（`日期`、`名稱`、`說明`）與 `data`（日期為 ISO）。OpenAPI 版只有當年度，查不到下一年，所以推算用網站版。
- **請求**：daily 的 trading_calendar 步驟（collect 成功後、analyze 之前，結果不影響 run 狀態，[日誌與 run 記錄](ops/SCHEDULING.md#日誌與-run-記錄)）與 `worker.cli trading-calendar`（[現有 worker CLI](ops/CLI.md#現有-worker-cli)），每次抓目標日的年度與下一年度，每天 2 個請求。不屬於 collect，不影響 collect 的核心／非核心狀態。
- **驗證與拒收**：`stat` 不是 `ok`、`queryYear` 不等於請求年度、`fields` 缺這三欄、某列欄數不符、日期無法解析或不在該年度、同一日期出現兩次、名稱為空，整份拒收，該年度不寫入，記在 run 的 `warnings` 與 `years.<年>`。`total=0`、`data` 為空代表該年度尚未公告（2026-10-26 查 2027 年即是如此），不寫入。被拒收或空的回應仍照常存 raw 當證據，只是不寫入日曆表。
- **分類**：名稱含「開始交易」「最後交易」為交易日提示（例：國曆新年開始交易日）；名稱或說明含「放假」「補假」「休市」「無交易」「不交易」為休市（含「市場無交易，僅辦理結算交割作業」與補假日）；兩者都不是記 `unknown` 並警告。2024～2026 年 71 列全部能分類。休市表沒有列出的週間日就是交易日。
- **保存**：`trading_calendar_days` 每個（`exchange`、`calendar_date`）一列：`year`、`kind`（`closed`／`trading`／`unknown`）、`name`、`description`、`source`（`twse_holiday_schedule`）、`collected_at` 與 `raw_payload_id`。raw 照一般規則保存（`run_type=trading_calendar` 的 ingestion run）；回應的 SHA-256 與該端點最近一次已存的 raw 相同時不另存；因為只比最近一份，內容在「有效、空或拒收、有效」之間交替時，同樣的有效內容會再存一份 raw（日曆列內容沒變，仍指向第一份）。內容有差異時整年改寫，該年所有列改指向這份 raw，新增、改分類與移除的日期記在 run 的 `years.<年>`；內容相同時列不動。已有列的年度回應變成空的，保留舊列並警告。
- **推算**：從 T 的隔天往後找第一個不是週末、也不是休市列的日期（最多 31 天）；碰到沒有列的年度（尚未公告或沒抓到）或 `unknown` 列就沒有答案，訊號的日期留空（規則見 [價位、ETF 與生命週期](spec/README.md#價位etf-與生命週期)）。
- **限制**：颱風等臨時休市不在休市表（2024 年 5 天颱風停市與 2026-10-23 都沒有列入），推算不知道，事後也不改寫；確認的臨時休市只記在 daily run 的 `non_trading_day`。官方年中修訂休市表時（例如新增假日），之後算的日期跟著新內容，之前存的訊號不改。

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

#### 寫入防呆

每列寫入前（daily 與回補都經 `worker.pipeline._upsert_action`），比較由欄位算出的因子與官方價格比 `減除股利參考價 ／ 除權息前收盤價`（TPEx `DividendDeductedQuote`／`ClosePriceBeforeExRightsDiviend`；TWSE `TWT49U` 的同名欄）。

- **比較方式**：在價格上比，`|欄位因子 × 除權息前收盤價 − 減除股利參考價| > 0.02 元` 判為不符（`ACTION_REFERENCE_TOLERANCE`）。
- **門檻依據**：官方參考價以 0.01 元公布且無條件捨去（TWSE 4912 2026-09-10：97.50 − 0.800477 = 96.6995，公布 96.69），正確的列差距小於 0.01。
- **不比除權息參考價**：用減除股利參考價，不用含現金增資認購的除權息參考價。欄位沒有現增，所以 3691 2026-10-27（現增認股）是 109.00／109.00 ＝ 1，不會被擋；現增由價格還原改用除權息參考價處理（[還原因子](spec/indicators.md)，#394）。
- **不符時**：該列照存 raw 與 `details_json`（加 `factor_check`），但 `cash_dividend`、`stock_dividend_ratio`、`split_ratio` 留空，錯的欄位不進價格還原；有官方除權息價格的列改以官方比還原（[還原因子](spec/indicators.md)）。另寫一列 `data_quality`（`entity_type=corporate_action`、`entity_key=<交易所>:<代號>:<action_type>`、`as_of_date` 為除權息日、`status=factor_mismatch`，`checks_json` 記兩邊的值）。之後同一事件寫入正確值時，這列改為 `complete`。
- **沒有官方價格的列**（daily 的 `TWT48U_ALL`）：不比，照舊寫入；之後的回補會以 `TWT49U` 覆寫並核對。
- **已核對的列不被覆寫**：同一事件（標的、日期、`action_type`）已有帶官方價格且通過核對的列時（回補寫入的，或 TPEx daily 寫入的），沒有官方價格的列（daily 的 `TWT48U_ALL` 重抓）整列不寫，因子、`details_json` 與 raw 連結都不變；daily 只新增還沒有的事件。沒有官方價格的既有列照舊由 daily 覆寫。

#### 除權息回補

`worker.cli corporate-actions sync`（[現有 worker CLI](ops/CLI.md#現有-worker-cli)）每個日曆月發一個請求，raw 每份回應只登錄一列，`data_as_of` 寫它涵蓋的區間（例如 `2026-09-01~2026-09-30`）。

| 來源 | URL | 用到的欄位 |
| --- | --- | --- |
| TWSE 除權除息計算結果表 | `https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate=YYYYMMDD&endDate=YYYYMMDD&response=json` | `資料日期`、`股票代號`、`股票名稱`、`除權息前收盤價`、`除權息參考價`、`權值+息值`、`權/息`、`減除股利參考價`。區間內沒有事件時只回 `stat`「很抱歉，沒有符合條件的資料!」。 |
| TWSE 計算結果明細 | `https://www.twse.com.tw/rwd/zh/exRight/TWT49UDetail?STK_NO=<代號>&T1=YYYYMMDD&response=json` | `(每股配發現金股利)除息`（`3 元／股`）、`A. 按普通股股東持股比例每千股無償配股`（`100 股`）；其餘現增欄位只保存。只對 `權/息` 含「權」的列請求。 |
| TPEx 除權除息計算結果表 | `https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ?startDate=YYYY/MM/DD&endDate=YYYY/MM/DD&response=json` | 21 欄（`除權息日期`、`代號`…`按持股比例仟股認購`）逐一對應 `tpex_exright_daily` 的英文欄名後，以 daily 同一個 parser 解析；回應的 `date` 須等於請求區間。 |

- **TWSE 對應**：`息` 列的現金股利是 `權值+息值`；含「權」的列取明細的每股現金股利，配股率見下一點。明細讀不到時該事件不寫入、記 warning，run 為 `partial`。`details_json` 保留 `TWT49U` 全部欄位、`detail` 與 `detail_sha256`，並補 `Code`／`Date`／`Name`／`Exdividend`，讓上面的分類照常運作。
- **TWSE 配股率**（`sources._twse_stock_ratio`）：明細的每千股無償配股只印到小數一位（2442 2026-09-08 印 `71.1 股`，實際 0.07111516），印出值 ÷ 1,000 最多差 0.00005。TWSE 用精確比率算參考價，所以從同一列的價格反推：沒有現增時 `(除權息前收盤價 − 現金股利) ／ (除權息前收盤價 − 權值+息值) − 1`（`權值+息值` 六位小數、未捨去）；明細有現增（`C. (有償) 現金增資` 或 `按股東持股比例每千股認購` 大於 0）時，分母改用不含認購的 `減除股利參考價`。存哪個值：
  - 反推值與印出值相差不到 0.000001：存印出值（`used=printed`）。
  - 相差不超過半個印出單位（0.00005）：存反推值（`used=derived`，精度為 TWSE 計算時用的比率）。
  - 相差更多：存印出值，標 `disagrees=true`，交由寫入防呆判斷（印出值與價格不一致就會被擋）。
  - 沒有印出值、沒有收盤價或現金股利、分母不是正數：存印出值、不反推。
  - `details_json.stock_ratio_source` 記 `printed`、`from`（`權值+息值` 或 `減除股利參考價`）、`derived`、`used` 與 `disagrees`。`disagrees` 的例子：8104 2025-09-16、1529 2026-07-21、2614 2026-10-06（有現增，印出值都通過價格核對）。
- **與 daily 同一列**：`action_type` 與 daily 的規則相同（TWSE 一律 `corporate_action`，TPEx 含「息」為 `ex_dividend`），所以回補覆寫 daily 寫的同一列，不會多出第二列。
- **拒收**：回應區間或列的日期不在請求區間內、欄位缺漏、`stat` 不是成功時，整次 sync 失敗、不寫 DB。

### 重大訊息日期查詢

MOPS `t05st02`（[#464](https://github.com/YiCheng0608/stock-lab/issues/464)）一次 POST 回一個日曆日的全市場重大訊息清單，`t187ap04_L`／`mopsfin_t187ap04_O` 只是最新公告的快照，不能證明某日沒有公告，所以事件覆蓋只看這個來源（`worker.mops_events`）。

- **請求**：body `{"year":"<民國年>","month":"MM","day":"DD"}`，每個查詢日 1 個請求；同一 host 間隔至少 3 秒（`OFFICIAL_HOST_MIN_INTERVAL_SECONDS`）。raw 存在 `mops` 來源，`data_as_of` 是查詢日。
- **回應**：`code=200`、`message=查詢成功`，`result.titles` 依序為 發言日期、發言時間、公司代號、公司名稱、主旨、詳細資料；`result.data` 每列是這六欄，第六欄的 `parameters.marketKind` 是 `sii`（上市）、`otc`（上櫃）、`rotc`（興櫃）、`pub`（公發）。只取 `sii`／`otc`，分別寫成 TWSE／TPEx 的事件。
- **時間範圍**：查 D 日的清單含 D 日到查詢當下的公告，加上 D−1 日 17:30 之後的公告。事件日期一律用列上的發言日期，不是查詢日；D 日晚於查詢時間的公告，下一次查 D+1 日時寫入（唯一鍵去重）。覆蓋記錄查詢時間 `fetched_at`，覆蓋只對自己的查詢日（`query_date`）成立，不依 run 的 `data_as_of` 或狀態推定到別天。
- **補查週末與連假**：daily 只在週一到週五跑，週五與連假前一天的晚間公告在沒有人查的週六或假日清單裡。所以 collect 查完目標日後，也補查回看 14 個日曆日內、第一個已核實日之後、目標日之前所有還沒核實（含 partial）的日曆日（`worker.mops_events.gap_dates`），例如週一補查週六、週日，連假後第一天補查整段假日，前幾天查詢失敗的日子也一併重查。補查結果記在 collect run 的 `event_gap_coverage`；回看範圍內沒有任何已核實日時不補查，歷史由 `events backfill` 回補。
- **覆蓋判定**：回應成功且可讀時，有 D 日的 `sii`／`otc` 列就是已核實（`verified_dates`），沒有就是已核實空日（`empty_dates`）。傳輸失敗、`code` 不是 200、沒有表格、欄名改變、列的發言日期不是 D 或 D−1、缺代號或主旨時，D 日記 `partial`，不推定為空，也不寫該次的事件；warning 以 `MOPS event list unavailable` 開頭，是非核心。
- **與快照同一則**：同一標的、同日、同型別，發言時間相同、主旨相同（不計 #204 的「（發言時間 HH:MM:SS）」後綴）就是同一則。快照寫的列有說明全文時，日期清單不覆寫它；標題相同但發言時間不同時另存一列，標題加發言時間。
- **寫入時機**：daily 與 catchup 的 collect、回補（`OfficialMarketDataAdapter`）都查目標日；另可用 `events backfill` 只回補事件（[CLI](ops/CLI.md#現有-worker-cli)）。`mops_events` 資料品質列在已核實時為 `complete`，之後的失敗不把它降回 `partial`；跨 run 讀覆蓋時，同一日以較強的證據為準（已核實／空日 > partial > 快照的 unsupported，同級取較新的 run）。

### 季度財報回補

`t187ap14_L`／`mopsfin_t187ap14_O` 只有最新一季，`fundamental_snapshots` 原本只有 1～2 季。MOPS「彙總報表－綜合損益表」`t163sb04` 一個請求回一個市場、一季的全部公司，`worker.cli fundamentals backfill`（[CLI](ops/CLI.md#現有-worker-cli)）用它回補近 8 季（[#529](https://github.com/YiCheng0608/stock-lab/issues/529)，實作在 [`worker/quarterly_fundamentals.py`](../backend/worker/quarterly_fundamentals.py)）。

- **請求**：新版 MOPS 的 `t163sb04` 頁沒有資料 API，它向 `api/redirectToOld` 要一個加密參數的舊站網址再開新視窗，資料就是舊站的 HTML。所以直接 POST 舊站 `https://mopsov.twse.com.tw/mops/web/ajax_t163sb04`，form 是 `encodeURIComponent=1&step=1&firstin=1&off=1&isQuery=Y&TYPEK=<sii|otc>&year=<民國年>&season=<01～04>`。上市、上櫃每季各 1 個請求，8 季共 16 個；同一 host 間隔至少 3 秒（`OFFICIAL_HOST_MIN_INTERVAL_SECONDS`）。raw 存在 `mops` 來源，內容是 endpoint、form 與 HTML 原文包成的 JSON，`data_as_of` 是季底日。
- **表格**：回應依產業格式分成多張 `table.hasBorder`，第一、二欄是「公司代號」「公司名稱」，最後一欄是基本每股盈餘。頁首註2寫明各季是「該年度截至該季止之累計金額」，單位新台幣仟元，與快照的口徑、單位相同；`--` 是無資料，留空。
- **營收欄**：取快照「營業收入」對應的欄位（2026-06-30 季兩市場 1,983 檔與快照逐檔比對，營收與 EPS 全部相同）。

  | 格式（以表頭判斷） | 營收 | 申報期限（Q1／Q2／Q3） |
  | --- | --- | --- |
  | 一般（有營業收入、營業毛利） | 營業收入 | 5/15、8/14、11/14 |
  | 其他（收入、支出；和泰車、三商等一般公司） | 收入 | 同一般 |
  | 銀行及票券（利息淨收益、利息以外淨損益） | 利息淨收益＋利息以外淨損益 | 5/15、8/31、11/14 |
  | 金控（利息淨收益、利息以外淨收益、淨收益） | 淨收益 | 5/30、8/31、11/29 |
  | 證券（收益、支出及費用） | 收益 | 5/15、8/31、11/14 |
  | 保險，IFRS 17（保險服務結果、財務結果；2026 年起） | 無，留空 | 5/15、8/31、11/14 |
  | 保險，舊格式（營業收入、沒有營業毛利；2025 年以前） | 營業收入 | 同上 |

  年度（Q4）一律隔年 3/31。表頭不屬於上列任一種、欄位數不符、同一代號出現兩次、頁首的市場或季別與請求不符、或回應是「FOR SECURITY REASONS」之類的阻擋頁時，整個市場季記失敗、不寫入。沒有表格但寫「查無資料」是已回答的空季。
- **可得日**：回補的季度沒有實際公告日，`announcement_date` 用該格式的法定申報期限，期限不是交易日時順延到下一個交易日（註1第 6 點「遇例假日以證期局公布者為準」）：有 [`trading_calendar_days`](#交易日曆) 的年度照官方休市表，沒有的年度只順延週末；`data_json` 記 `announcement_basis: statutory_deadline`、`statutory_deadline` 與 `deadline_calendar`（`twse_holiday_schedule`／`weekend_only`）。期限還沒到的季度（例如 11/6 時的第三季，已申報的公司先列出）用抓到那天的台北日期，`announcement_basis: first_seen`，不寫未來日期。可得日的意思是「該日結束後可得」：研究截止日期等於可得日時就列入，對應 T 日晚上收集、分析，T+1 才執行；所以期限日當晚才申報的財報，會被當晚的分析用到。這和日快照的出表日期是同一個口徑，因此不另外順延到下一個交易日。逾期申報的公司會比實際早「可見」，這種公司很少，但不是 0。網站版休市表只提供今年與前一年（2026-11-06 查 2024 年回非 JSON），回補前先跑 `trading-calendar --year <前一年>`。
- **首見出表日**：快照每次重新出表都會換「出表日期」（2330 第二季曾存成 2026-10-30，實際 8 月就公告）。現在同一季遇到既有列時，可得日取既有與新值中較早的那個；保留舊日期時一併保留它的 `announcement_basis` 等欄位。營收、EPS 照舊以最新一次為準。已知限制：財報重編或更正後，數值換成新的，可得日仍是最早那天，所以截止日在重編之前的回測，會提早看到重編後的數字。例外：既有與新值都是法定期限時，用重新算的期限，休市表之後才補上時，重跑會把期限更正成順延後的日期。
- **與快照並存**：唯一鍵 `(instrument_id, period_end, fiscal_period)` 不變，不會多列。回補遇到快照寫的列，不改數值與來源，只在法定期限較早時把可得日往前調；回補寫的列由回補更新數值。之後日快照涵蓋同一季時，照上一點覆寫數值、保留較早的可得日。
- **冪等**：數值、可得日與 `data_json` 都沒變的列不寫（`raw_payload_id`、`collected_at` 也不動，列指向它的數值來自的那次 capture），重跑時 `changed` 是 0。HTML 含當次產生的 CSV 檔名，每次抓的 SHA-256 都不同，raw 每次都存。
- **實測**（2026-11-06，正式 DB 副本，alembic `0027_emerging_issuers`）：16 個請求約 66 秒；2024Q4～2026Q2 每季 1,930～1,986 檔，2026Q3 當時 283 檔；重跑 `changed 0`。
- **daily 自動回補**（[#536](https://github.com/YiCheng0608/stock-lab/issues/536)）：日快照換季後（2026Q2 在 11-02 換成 Q3）不再更新上一季，所以換季後才上市的公司（2026Q2 的 7867 特力屋，10-30 上市）、晚申報與更正都收不到。daily 的 period_backfill 步驟在每季最早期限前 14 天到最晚期限後 14 天之間（Q3 是 10/31～12/13）每天補該季與前一季，窗口、上限與記錄見 [SCHEDULING](ops/SCHEDULING.md#日誌與-run-記錄)。快照落後的期別不算漏：2026Q3 回補在 11-06 早上比 11-05 的快照多 85 檔，11-06 的上市快照就全部列入了。

### 月營收

個股頁財務分頁的「月營收」表讀 `monthly_revenues`，每家公司每月一列（唯一鍵 `(instrument_id, revenue_month)`，`revenue_month` 存該月 1 日）；不納入策略與評分（[#530](https://github.com/YiCheng0608/stock-lab/issues/530)，實作在 [`worker/monthly_revenue.py`](../backend/worker/monthly_revenue.py)）。

- **欄位與單位**：`revenue`（當月營收）、`prior_year_revenue`（去年當月營收）、`cumulative_revenue`（當月累計營收）是千元；`yoy` 是來源的「去年同月增減(%)」，不自己重算：快照是全精度，MOPS 頁截斷到小數 2 位（2330 115/09 為 54.6486 → `54.64`）。上月營收、上月比較、去年累計、前期比較、備註存 `data_json`。來源是空白（上月或去年同月為 0）時存 NULL，不補 0。
- **每日快照**：collect 抓 `t187ap05_L`、`mopsfin_t187ap05_O`，各 1 個請求。兩份都只有一個月（`資料年月`），整份共用一個 `出表日期`；例如 2026-11-06 抓到的仍是 10/17 出表的 9 月表，10 月要等申報期限 11/10 之後才換。可得日用出表日期，`data_json.announcement_basis = release_date`。列的 `資料年月` 不一致、同一代號兩次、出表日期讀不到或不在該月之後時整份不寫；出表日期晚於收集日的列略過（回補舊日期時不讀今天的表）。取得、解析或寫入失敗是非核心 warning（`TWSE monthly revenue unavailable`／`TPEx …`），collect 仍為 `success`，各交易所分開寫，一邊失敗不影響另一邊。
- **回補**：`worker.cli revenue backfill`（[CLI](ops/CLI.md#現有-worker-cli)）抓 MOPS 營業收入統計表靜態頁，預設上個月往回 24 個月，每個市場月 2 頁，共 2 × 2 × 24 = 96 個請求，同一 host 間隔至少 3 秒。`_0` 只有國內公司；國外公司（`-KY`、`-DR`）在 `_1`，兩頁不重疊（115/09 上市 997＋94、上櫃 867＋30 檔，合起來涵蓋快照的全部公司）。頁面是 Big5（cp950），raw 存 `mops` 來源，內容是 URL 與解碼後的 HTML，`data_as_of` 是月底日。頁首的「出表日期」是當天產生頁面的日期，不是申報日，不使用。MOPS 偶發 `502 Unreachable Server`（探路時等 10 秒重試就成功），傳輸錯誤、429 與 5xx 依序等 5、10、20 秒各重試一次；仍失敗記該頁失敗，連續 3 頁失敗停跑，重跑可補。`_0` 與 `_1` 若出現同一代號，留先讀到的那頁、後一頁的列不寫，記 warning（run 為 `partial`）。
- **頁面格式**：每個產業一張表，欄位依序是公司代號、公司名稱、當月營收、上月營收、去年當月營收、上月比較增減(%)、去年同月增減(%)、當月累計營收、去年累計營收、前期比較增減(%)、備註，與快照同口徑；每表最後的「合計」列與頁尾的「全部國內／國外上市（上櫃）公司合計」不是公司。標題不是請求的市場與月份、頁尾總計不是請求的國內／國外頁、表頭改變、公司列不是 11 格、同一代號兩次，或回應是阻擋頁時，整頁記失敗、不寫入。
- **可得日**：回補的月份沒有申報時間，`announcement_date` 用法定期限次月 10 日（證券交易法第 36 條），遇休市順延到下一個交易日，順延規則同[季度財報回補](#季度財報回補)（有 `trading_calendar_days` 的年度照官方休市表，沒有的只順延週末）；`data_json` 記 `announcement_basis: statutory_deadline`、`statutory_deadline`、`deadline_calendar`。回補前要先有對應年度的休市表（`trading-calendar --year <年>`），缺的話會退回只順延週末（`deadline_calendar: weekend_only`），例如 2025-10-10 國慶會記成當天而不是 10/13；網站版休市表抓不到 2024 年，2024 年用到的期限只有 2024-12-10，是平日。期限還沒到的月份（例如 11/6 跑時的 10 月，已申報的公司先列出）用抓到那天的台北日期，`announcement_basis: first_seen`。可得日的意思同季報：該日結束後可得，研究截止日期等於可得日時列入。逾期申報的公司會比實際早「可見」。
- **兩個來源同一個月**：照季度回補的規則。回補遇到快照寫的列，不改數值與來源，只在期限較早時把可得日往前調（9 月快照的 10/17 調成 10/12，10/10 是週六）；回補寫的列被快照涵蓋時，數值與來源換成快照的，可得日保留較早的那個與它的依據。快照出表後更正的數字，MOPS 頁會更新、快照不會（115/09 有 7 檔不同，例如 4426 利勤），同月以快照為準。
- **冪等**：數值、來源、可得日與它的依據都沒變的列不寫（`data_json`、`raw_payload_id`、`collected_at` 也不動），重跑 `changed` 是 0；快照換了出表日期但數字相同時也不寫。
- **daily 自動回補**（[#536](https://github.com/YiCheng0608/stock-lab/issues/536)）：月快照出表後到下個月換表前不再更新，例如 9 月表 10-17 出表、到 11 月 10 月表出來前都是那一份。2026-11-06 比對時，10-20～10-30 上市的 7 檔新股（2249、6825、6898、6938、6467、7710、7867）的 9 月營收只在 MOPS 頁上有；期限前已申報的下個月（11-06 時 10 月有 289 檔）也要等換表才進快照。daily 的 period_backfill 步驟在每月 1～20 日每天補上個月與上上個月，窗口、上限與記錄見 [SCHEDULING](ops/SCHEDULING.md#日誌與-run-記錄)。出表後更正的數字仍依「兩個來源同一個月」以快照為準，自動回補不會改回 MOPS 頁的值。

## FinMind 補缺口規則

- FinMind（`https://api.finmindtrade.com/api/v4/data`）只用免費方案補官方來源沒有的歷史與缺日；目前 collector 未接 FinMind。
- 用途限本機個人非商用盤後研究；署名，不鏡像、不再散布 raw。
- FinMind 回 401／402／403 或要求付費、登入即停止，不在同一次取得內重試。
- FinMind 是服務提供者，不是官方直接來源：每筆保存來源 `finmind`、資料集名稱與擷取時間；不覆寫已存在的官方值，同一欄位不混用兩個來源；單位與 scale 依資料集文件判讀並在該資料集規則中寫明。
- 付費資料集不使用。
