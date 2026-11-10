# 今日可買 `/`（含大盤 `/market`）

入口：主導航「今日可買」（`MAIN_NAV` 第一項，#493 前叫「今日」），`TodayPage`（`frontend/src/App.tsx`）；`MAIN_NAV` 在 `frontend/src/components/Navbar.tsx`。

大盤頁 `/market`（主導航「大盤」，`MAIN_NAV` 第二項，`MarketPage`，`frontend/src/market/MarketPage.tsx`）也歸這個檔（#549）：它是從今日可買頁拆出的大盤概況，讀同一支 `dashboard.market_overview`（#547 起含美股指數的 `foreign_indices`，#564 起含指數總表的 `indexes`），今日可買頁只留一行摘要連過去，兩頁一起驗。#564 起大盤頁只有一張共用的日 K（總表選中的指數，網址 `?index=`），所以另拍 `?index=tpex`、`?index=tx` 兩張 1280 截圖驗另外兩檔台股的圖與網址選擇。

## API

| 檔名 | URL（前綴 `<API>/api`，`<API>` 為 API 的 origin） |
| --- | --- |
| `dashboard.json` | `/dashboard` |
| `today-board.json` | `/themes?board=industry&limit=5` |
| `candidates.json` | `/candidates` |
| `news-<id>.json` | `/news/<id>`，`dashboard.json` 的 `news` 前 3 則各一個 |
| `taiex-bars.json` | `/stocks/TWSE/TAIEX/bars?interval=day&limit=250`（大盤頁預設的加權指數日線） |
| `tpex-bars.json` | `/stocks/TPEx/TPEX/bars?interval=day&limit=250`（`/market?index=tpex` 的櫃買指數日線，#552、#564） |
| `tx-bars.json` | `/stocks/TAIFEX/TX/bars?interval=day&limit=250`（`/market?index=tx` 的台指期近月日線，#552、#564） |

## 驗證範圍

改到下列前端檔或 API route 時，CI 驗這一頁；規則見 [README 驗證範圍](README.md#驗證範圍)。

| 種類 | 對象 |
| --- | --- |
| 前端檔 | `frontend/src/candidates/CandidateViews.tsx` |
| 前端檔 | `frontend/src/today/TodayViews.tsx` |
| 前端檔 | `frontend/src/market/MarketPage.tsx` |
| 前端檔 | `frontend/src/market/MarketViews.tsx` |
| 前端檔 | `frontend/src/market/marketOverview.ts` |
| 前端檔 | `frontend/src/stock/StockBarsChart.tsx` |
| 前端檔 | `frontend/src/news/NewsViews.tsx` |
| 前端檔 | `frontend/src/themes/ThemeViews.tsx` |
| 前端檔 | `frontend/src/tracking/TrackingViews.tsx` |
| 前端檔 | `frontend/src/actions/actionTiers.ts` |
| 前端檔 | `frontend/src/stock/strategyBoard.ts` |
| API route | `GET /dashboard` |
| API route | `GET /themes` |
| API route | `GET /candidates` |
| API route | `GET /news/{news_id}` |
| API route | `GET /stocks/{exchange}/{symbol}/bars` |

## 截圖

`--url <WEB>/ --name today`、`--url <WEB>/market --name market`（各 1280 與 390）；`--url <WEB>/market?index=tpex --name market-tpex`、`--url <WEB>/market?index=tx --name market-tx`（只 1280，#564）。

## 預期資料與標記

| 區塊 | 資料來源 | 必須顯示的來源與資料日期 | 「推論」位置 | 空資料文案 |
| --- | --- | --- | --- | --- |
| 導覽列 | `dashboard.as_of` | `資料 <D/>`（右上 badge） | — | `資料日期未提供`；`/api/dashboard` 失敗時 `資料日期暫時無法載入`（#465） |
| 頁首資料列 | `dashboard.as_of`、`market.source_label`、`mode` | 一行 `資料截至 <D/> · <來源> · <模式>`；「資料說明」內 `成交金額範圍：…` | — | 模式 `尚無官方快照` |
| 大盤摘要列 | `dashboard.market_overview` | 一行 `加權 <收盤> <±漲跌幅%>`、`櫃買 …`、`資料 <market_overview.trading_date>`、`看大盤 →`（#549） | — | `加權 未取得`／`櫃買 未取得` |
| 持倉風險提示列 | `dashboard.actions` 的持倉風險 | — | — | 沒有持倉風險時不出現 |
| 今日可買 | `candidates.json` | 標題下 `資料 <C/>` 與 `<n> 檔`；每列 `#<名次>`；每列明細 `資料日期 <C/>`、`來源：…`；每列明細一行 `加入追蹤`（按鈕）或 `已在追蹤`（連到觀察中的計畫） | 新聞情緒分項與理由後的 `推論`；每列 AI 入口 `AI 推論 ▸`（有 `llm_note`）或 `AI 說明 ▸`；明細的 `AI 推論` 說明區；來源行結尾 `（推論）` | `當日零候選`／`尚無候選清單` |
| 大盤頁：大盤概況 | `dashboard.market_overview` | 標題 `大盤概況` 下一行 `資料 <market_overview.trading_date>`；加權指數、櫃買指數、成交金額（億元）、漲跌家數；資料日同 `D`；「資料說明」內來源與 `成交金額範圍：…`；四格之下一條 `加權指數與季線（MA60）`（`market_overview.taiex_ma60`，#561）：`加權指數 <收盤>（<D/>）<在季線之上／在季線之下／與季線持平>（季線 <MA60>）` 與近 250 個交易日內最近 3 段在季線之上的區段（頁面檢查未涵蓋這條，靠前端測試與後端 API 測試） | — | `上市大盤資料未取得`／`上櫃大盤資料未取得`；`季線資料不足：…`／`季線無資料：…` |
| 大盤頁：指數總表 | `dashboard.market_overview.indexes` | 在 `大盤概況` 與 K 線卡之間，標題 `指數總表` 下一行 `資料 <market_overview.trading_date>`；分組 `台股`（加權指數、櫃買指數、台指期近月）與 `美股`（每個有資料的美股列都是台股資料日前一個美股交易日時 `美股（前一交易日）`；S&P 500、NASDAQ 綜合指數、道瓊工業指數、費城半導體指數）；每列一行：名稱（台指期接 ` 合約 YYYY/MM`）、收盤（點，指數兩位小數、台指期整數）、漲跌、漲跌幅（換月日兩格都是 `換月`）、資料日（`stale` 接 ` 非最新`，`us_market_closed` 接 ` <expected_date> 美股休市`）、相對季線（`之上／之下／持平 季線 <ma60>`、`資料不足（n／60 日）`、`無資料：…`）、來源；「資料說明」內臺灣期貨交易所與 FRED 的顯名（#564） | — | 該列 `無資料：尚未收集`／`無資料：尚無已驗證的資料日`／`無資料：最近一次擷取失敗（<日期>）`，數值格 `—` |
| 大盤頁：共用 K 線圖 | `taiex-bars.json`（`market`）、`tpex-bars.json`（`market-tpex`）、`tx-bars.json`（`market-tx`） | 指數總表之後一張個股頁的 K 線卡（`StockBarsChart`），卡標題是選中列的 `<名稱>日線`（預設 `加權指數日線`），標題下一行 `資料 <data_as_of>`；`最近 <count> 根日線；缺日不補、停牌不畫 K 線`；資料表最新一根（單位「點」，指數兩位小數、台指期整數）；台指期卡最後有開放資料顯名；美股卡只畫收盤線，卡底 FRED 顯名與版權標示（#547、#564） | — | `無資料`＋`來源未提供日線` |
| 熱門族群 | `today-board.json` | 榜別分頁下一行 `資料 <B/>`；每列 `資料 <B/> · 相對加權指數` | — | `meta.empty_message` 或 `此榜目前沒有族群` |
| 重點新聞 | `dashboard.news` 前 5 則（只收有關聯或有判讀的新聞，不足照實際數量，[NEWS_SPEC 首頁重點新聞](../../../../docs/NEWS_SPEC.md#首頁重點新聞)） | 每則：來源 badge、`發布於／事件於／事件日 …` 時間 | 有 AI 判讀的卡在方向後接 `AI 推論` | `市場新聞區尚無可顯示內容。` |

`D` = `dashboard.as_of` 前 10 字；`B` = `today-board.json` 的 `meta.trading_date`；`C` = `candidates.json` 的 `trading_date`。

## 檢查

| 編號 | 類型 | 檢查 | 怎麼判 |
| --- | --- | --- | --- |
| T1 | CI | 頁面可用 | `today`、`market` 兩張截圖兩個寬度與 `market-tpex`、`market-tx` 的 1280 都 `ready` true、`httpErrors` 與 `consoleErrors` 空、`overflow` false |
| T2 | CI | 導覽列資料日 | `today-1280.txt` 有整行 `資料 <D/>`，且 `D` 等於 `facts.json` 的 `market_latest_trading_date`。`D` 缺少時：`market_latest_trading_date` 非 null 判失敗（DB 有行情、頁面沒有資料日），兩邊都沒有才查整行 `資料日期未提供`。`D` 的上游 |
| T3 | CI | 頁首資料列 | 第一個 `資料截至 ` 開頭的行以 `資料截至 <D/> · ` 開頭，其後以 ` · ` 分出來源與模式兩段且都非空；來源等於 `market.source_label`（null 時只要求非空）。`D` 的上游 |
| T4 | CI | 熱門族群日期 | 整行 `熱門族群` 之後第一個 `資料 ` 開頭的行是 `資料 <B/>`；`B` 等於 `facts.json` 的 `group_scores_latest_trading_date`。`B` 缺少時：`group_scores_latest_trading_date` 非 null 判失敗，兩邊都沒有才查整行 `資料日期未提供`。`B` 的上游 |
| T5 | CI | 熱門族群列 | 整行 `資料 <B/> · 相對加權指數` 的行數 = `min(5, items 數)`（今日頁各榜前 5）；`items[0].display_name` 為整行出現。`items` 空時：`facts.json` 的 `group_scores_latest_trading_date` 非 null 且等於該榜 `meta.trading_date`（或後者為 null），或 `dashboard.json` 的 `groups` 有該日 `rank` 非 null 的族群，判失敗；都沒有才查空資料文案。`T` 的上游；`B` 用 T4 |
| T6 | CI | 新聞卡與 AI 標記 | `dashboard.news` 前 5 則的顯示標題（`display_title(title)`，同 [news N2](news.md)）各為整行出現；其中 `news-<id>.json` 的 `ai.status` 為 `done` 且 `ai.inference` 為 true 的：`dashboard.news` 該則的 `ai` 與它相同，卡片有整行 `AI 推論`，其上一行（方向行）等於 AI 方向（`ai.unsupported` 為 true 時是 `影響尚未判定`，否則 `ai.impact_direction` 照 positive／negative／mixed 寫 `可能正向`／`可能負向`／`正負互見`，其餘 `影響尚未判定`；與新聞頁同一套，#233）。一張卡的範圍是它的標題行到下一則標題行之前；最後一則到其後的頁尾第一行 `T 日收盤訊號 · 最早 T+1 執行 · T+5／T+20 追蹤` 之前（#493 起新聞是首頁最後一區） |
| T7 | CI | 今日可買日期、名次列與來源 | `status` 不是 `not_computed` 且 `items` 非空時：標題 `今日可買`（整行 `條件已成立 · 依評分排序` 之後的第一個整行 `今日可買`；導覽列也有一行 `今日可買`）的下一行是 `資料 <C/>`、再下一行 `<candidate_count> 檔`；標題與 `熱門族群` 之間以 `#<n> <代號> ` 開頭的名次列（表格股票欄的第一行，#493；熱門族群列的 `#<n>` 自成一行，不算）依序等於 `items[].rank`（收合的其餘幾檔在截圖展開 `<details>` 後也列出）；`^來源：` 行數 = `items` 數，且 `C` 等於 `facts.json` 的 `candidate_run_latest_trading_date`。`items` 空時整行 `當日零候選`，`not_computed` 時整行 `尚無候選清單`；但 `facts.json` 的 `candidate_count_latest` > 0 且 `candidate_run_latest_trading_date` 等於 `candidates.json` 的 `trading_date`（或後者為 null）時判失敗 |
| T8 | CI | 今日可買推論標記 | 在 T7 之後（T7 沒通過時 T8 的失敗記「無法判定（上游 T7）」）。第 i 個 `^來源：` 行對應 `items[i]`（卡片依名次排列）；`components.news_sentiment.inference` 為 true 的候選，其來源行結尾為 `（推論）`；說明區標題 `AI 推論` 的整行數 ≥ `items` 數；免責句 `由 AI 依上方規則數值、理由與關聯新聞撰寫的推論，不是買賣建議；價位以規則數值為準。` 的行數 = `items` 數；AI 入口 `AI 推論 ▸` 的個數 = `llm_note` 不為 null 的檔數，`AI 說明 ▸` 的個數 = 其餘檔數 |
| T9 | CI | 首頁只有一份名單 | 沒有整行 `關注標的`、`查看個股詳情 →`、`查看行動中心 →`、`明日候選`（#493：關注標的移到觀察中，持倉風險提示列連到 `查看觀察中 →`） |
| T10 | 人工 | 候選進出點說明 | 樣本：`candidates.json` 依名次前 3 檔（`manual/T10.json`）。每檔 `llm_note` 寫到的價位（進場、突破、拉回區間、停損、目標）都等於 `levels` 的對應值，進場方式與 `levels.entry_type` 一致，沒有 `levels` 以外的價位、保證或買賣指示；`llm_note` 未完成的那檔記無法判定。一檔不符即失敗，證據寫代號、說明原句與 `levels` 值 |
| T11 | CI | 大盤頁的大盤概況 | 讀 `market-1280.txt`（#549 起大盤概況在大盤頁）。整行 `大盤概況` 的下一行是 `資料 <market_overview.trading_date 換成 YYYY/MM/DD>`（日期為 null 時 `資料日期未提供`）。`dashboard.market_overview` 每個交易所：`available` 時，`facts.json` 的 `market_summary_latest` 該交易所列的 `trading_date` 等於 `market_overview.trading_date`，且指數收盤、漲跌、成交金額、上漲與下跌家數與 API 相同；頁面有整行指數收盤（兩位小數、千分位；四捨五入同前端 `toFixed`，剛好 .5 時遠離零）、`<±漲跌>（<±漲跌幅>%）`、`<上市／上櫃> <成交金額÷1 億，兩位小數> <短範圍>`（`twse_all_securities` 為 `集中市場總計`、`tpex_stocks` 為 `上櫃股票`，其他值為 `scope_label`）、`<上市／上櫃> 上漲 n · 下跌 n · 平盤 n（漲停／跌停）`；「資料說明」有整行 `成交金額範圍：上市為<scope_label>；上櫃為<scope_label>`（只列 available 的交易所）。`unavailable` 時頁面有整行 `上市大盤資料未取得`／`上櫃大盤資料未取得`，但 `market_summary_latest` 該交易所列的日期等於 `market_overview.trading_date` 時判失敗 |
| T12 | CI | 區塊順序 | 標題 `今日可買`（同 T7 的定位）、整行 `熱門族群`、`重點新聞` 都在，且 `今日可買` 在另兩行之前（PRODUCT_SPEC §2） |
| T13 | CI | 加入追蹤 | 在 T7 之後。截圖展開每列明細；`items` 非空時，整行 `加入追蹤` 與整行 `已在追蹤` 的行數合計 = `items` 數，`已在追蹤` 的行數 = `items[].open_plan_id` 非 null 的筆數；`items` 空時兩種行都不出現 |
| T14 | CI | 今日可買的大盤摘要列 | `today-1280.txt` 有相連的四行：`加權 <收盤，兩位小數> <±漲跌幅，兩位小數>%`（`change_pct` 為 null 時 `—`；`unavailable` 或收盤為 null 時整行 `加權 未取得`）、同格式的 `櫃買 …`、`資料 <market_overview.trading_date 換成 YYYY/MM/DD>`（null 時 `資料日期未提供`）、`看大盤 →`；四行在標題 `今日可買`（同 T7 的定位）之前；頁面沒有整行 `漲跌家數（股票）`、`括號為漲停／跌停`（四格大盤概況已移到大盤頁） |
| T15 | CI | 大盤頁的共用日 K | 依序讀 `market-1280.txt`＋`taiex-bars.json`（預設）、`market-tpex-1280.txt`＋`tpex-bars.json`、`market-tx-1280.txt`＋`tx-bars.json`（`?index=` 選的列，#564）。每張截圖：有整行該列的圖標題（`加權指數日線`、`櫃買指數日線`、`台指期近月日線`），其他 6 檔的 `<名稱>日線` 都不出現（只有一張圖、網址選擇有效），標題在整行 `指數總表` 之後；台指期標題之後有整行 `資料來源：臺灣期貨交易所（政府資料開放平臺，政府資料開放授權條款第1版）`。API `bars` 非空時至少一根可畫（同前端 `isDrawableBar`：未停牌、開高低收都是正數且高、低包住開收；收盤-only 的列開＝高＝低＝收也算），標題的下一行是 `資料 <data_as_of 換成 YYYY/MM/DD>`，其後有整行 `最近 <count> 根日線；缺日不補、停牌不畫 K 線`，資料表（截圖展開）有一行以 `<最新一根可畫的日期 YYYY/MM/DD>`、tab、開、高、低、收（指數兩位小數、台指期整數，以 tab 分隔）開頭；`bars` 空時其後有整行 `來源未提供日線`。CI 假資料庫有三者的日線（台指期只有最後 10 個交易日、整數點，`fixture_data.TX_SESSIONS`） |
| T16 | CI | 大盤頁的指數總表 | 讀 `market-1280.txt` 與 `dashboard.json` 的 `market_overview.indexes`（7 列，`key` 依序 `taiex`、`tpex`、`tx`、`spx`、`ixic`、`dji`、`sox`）。整行 `指數總表` 在整行 `大盤概況` 之後、`加權指數日線` 之前；其後整行 `台股`，再後整行美股分組標題（每個有資料的美股列 `freshness` 為 `latest` 或 `us_market_closed` 且 `trading_date` 早於 `market_overview.trading_date` 時 `美股（前一交易日）`，否則 `美股`）。每列依序是一整行（儲存格以 tab 分隔）：名稱（台指期有 `contract_month` 時接 ` 合約 YYYY/MM`）、收盤（千分位，指數兩位小數、台指期整數）、漲跌（同位數、正數帶 `+`）、漲跌幅（兩位小數加 `%`、正數帶 `+`；`change_status=contract_roll` 時這兩格都是 `換月`；null 寫 `—`）、資料日（`stale` 接 ` 非最新`，`us_market_closed` 接 ` <expected_date> 美股休市`）、相對季線（`ma60.status=available` 時 `<之上／之下／持平> 季線 <ma60，同收盤位數>`；`insufficient` 時 `資料不足（<close_count>／<required_closes> 日）`；`unavailable` 時 `無資料：日線未收集`／`無資料：日線最新為 <日期>`／`無資料：季線尚未計算`，其他 `無資料`）、`source.label`；`unavailable` 的列是 `<名稱>\t—\t—\t—\t<原因>\t—\t<來源>`，原因 `無資料：尚未收集`、`no_verified_session` 為 `無資料：尚無已驗證的資料日`、`fetch_failed` 為 `無資料：最近一次擷取失敗（<last_attempt_date>）`。台股三列在美股分組標題之前、美股四列在它之後。`指數總表` 之後有整行臺灣期貨交易所顯名與 `資料來源：FRED，Federal Reserve Bank of St. Louis（個人非商業使用）`（資料說明，截圖展開）。CI 假資料庫 7 列都有資料（`fixture_data.EXPECTED`） |

## 陷阱

- 「有 AI 判讀」的定義見 [news.md 陷阱](news.md#陷阱)（T6）。
- 候選在 1280 是表格（640px 以下改卡片，1280 的頁面文字沒有卡片）：一列的儲存格以 tab 分隔，股票欄在行首，第一行是 `#<名次> <代號> <名稱>`（#493）；明細列在 `<details>` 裡，截圖展開後才有 `來源：`、AI 說明區與免責句（#276）。熱門族群列也有 `#<n>`，所以名次列只數 `今日可買` 與 `熱門族群` 之間。
- `dashboard.as_of` 帶時間，`D` 只取前 10 字。`D` 本身是 API 的 `-` 分隔日期，頁面上的 badge 一律是 `/` 分隔：導覽列 `資料 <D/>`、各卡片 `資料 <B/>`、`資料 <C/>` 等（UI_COPY_SPEC §1，#270）。

## 判定

- 通過：T1～T9、T11～T16 全部通過；T10 由人工判讀另記。
- 失敗：任一條失敗，列出編號、預期與實際。
- 無法判定：沒有失敗，但有檢查無法判定（API 非 200、截圖未 ready，或上游沒通過，見 [README 三態與上游](README.md#三態與上游)）；列出 URL 或上游編號。

## 輸出格式

```markdown
### 今日可買 `/`：失敗

| 檢查 | 結果 | 原因類別 | 證據 |
| --- | --- | --- | --- |
| T1 | 通過 | — | 1280／390 ready，無錯誤，無橫向捲動 |
| T2 | 通過 | — | `資料 2099-01-02` = facts 2099-01-02 |
| T4 | 失敗 | 產品缺陷 | `熱門族群` 後第一個資料行是 `資料 2099/01/01`，預期 `資料 2099/01/02`（today-1280.txt 第 58 行） |

截圖：shots/today-1280.png、shots/today-390.png
```

記下供後續檔案使用：`B`、`today-board.json` 的 `items[0].theme_id` 與 `display_name`（族群路徑的起點）。
