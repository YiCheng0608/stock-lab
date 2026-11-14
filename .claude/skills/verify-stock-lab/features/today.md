# 今日名單 `/`（含大盤 `/market`）

入口：主導航「今日名單」（`MAIN_NAV` 第一項，#493 前叫「今日」），`TodayPage`（`frontend/src/App.tsx`）；`MAIN_NAV` 在 `frontend/src/components/Navbar.tsx`。

大盤頁 `/market`（主導航「大盤」，`MAIN_NAV` 第二項，`MarketPage`，`frontend/src/market/MarketPage.tsx`）也歸這個檔（#549）：它是從今日名單頁拆出的大盤概況，讀同一支 `dashboard.market_overview`（#564 起含指數總表的 `indexes`；美股指數 #547 起在 `foreign_indices`，#681 起移到 `/api/candidates` 的 `overnight_us`，由今日名單頁的「隔夜美股」一行顯示），今日名單頁只留一行摘要連過去，兩頁一起驗。#564 起大盤頁只有一張共用的日 K（總表選中的指數，網址 `?index=`），所以另拍 `?index=tpex`、`?index=tx` 兩張 1280 截圖驗另外兩檔台股的圖與網址選擇。

## API

| 檔名 | URL（前綴 `<API>/api`，`<API>` 為 API 的 origin） |
| --- | --- |
| `dashboard.json` | `/dashboard` |
| `dashboard-groups.json` | `/dashboard?include=groups`（首頁不讀 `groups`，預設不帶，#601；只供 T5 的旁證） |
| `data-date.json` | `/data-date`（導覽列的資料日期，#601；CI 假資料庫核對它等於 `D`） |
| `today-board.json` | `/themes?board=industry&limit=5` |
| `candidates.json` | `/candidates` |
| `taiex-bars.json` | `/stocks/TWSE/TAIEX/bars?interval=day&limit=250`（大盤頁預設的加權指數日線） |
| `tpex-bars.json` | `/stocks/TPEx/TPEX/bars?interval=day&limit=250`（`/market?index=tpex` 的櫃買指數日線，#552、#564） |
| `tx-bars.json` | `/stocks/TAIFEX/TX/bars?interval=day&limit=250`（`/market?index=tx` 的台指期近月日線，#552、#564） |

## 驗證範圍

改到下列前端檔或 API route 時，CI 驗這一頁；規則見 [README 驗證範圍](README.md#驗證範圍)。

| 種類 | 對象 |
| --- | --- |
| 前端檔 | `frontend/src/candidates/CandidateViews.tsx` |
| 前端檔 | `frontend/src/today/TodayViews.tsx` |
| 前端檔 | `frontend/src/today/CandidateChart.tsx` |
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
| API route | `GET /data-date` |
| API route | `GET /themes` |
| API route | `GET /candidates` |
| API route | `GET /stocks/{exchange}/{symbol}/bars` |

## 截圖

`--url <WEB>/ --name today`、`--url <WEB>/market --name market`（各 1280 與 390）；`--url <WEB>/market?index=tpex --name market-tpex`、`--url <WEB>/market?index=tx --name market-tx`（只 1280，#564）；`--url <WEB>/ --name today-chart --widths 390 --click '.candidate-row[data-candidate-rank="1"] .candidate-chart-toggle'`（只 390，點開第 1 列的 K 線卡，#665）。

## 預期資料與標記

| 區塊 | 資料來源 | 必須顯示的來源與資料日期 | 「推論」位置 | 空資料文案 |
| --- | --- | --- | --- | --- |
| 導覽列 | `/api/data-date` 的 `as_of`（與 `dashboard.as_of` 同一個 helper，#601） | `資料 <D/>`（右上 badge；#661 起是每頁唯一的頁面日期，不收進手機選單，390 寬也在） | — | `資料日期未提供`；`/api/data-date` 失敗時 `資料日期暫時無法載入`（#465） |
| 頁首資料列 | `dashboard.as_of`、`market.source_label`、`mode` | 一行 `<來源> · <模式>`（#661：與頁面日期 `D` 同一天，不再寫 `資料截至 <D/> · `）；「資料說明」內 `成交金額範圍：…` | — | 模式 `尚無官方快照` |
| 大盤摘要列 | `dashboard.market_overview` | 一行 `加權 <收盤> <±漲跌幅%>`、`櫃買 …`、`資料 <market_overview.trading_date>`（與 `D` 同一天時沒有，#661）、`看大盤 →`（#549） | — | `加權 未取得`／`櫃買 未取得` |
| 持倉風險提示列 | `dashboard.actions` 的持倉風險 | — | — | 沒有持倉風險時不出現 |
| 今日名單 | `candidates.json` | 標題下 `資料 <C/>`（與 `D` 同一天時沒有，#661）與 `<n> 檔`；標題列下一行 `隔夜美股 …`（`overnight_us`，美股資料日寫在行內，#681）；每列 `#<名次>`；每列進場句下一條近 30 個交易日收盤的走勢線（`recent_closes`，SVG 帶 `aria-label`、沒有頁面文字，#653）；每列明細 `資料日期 <C/>`（與 `D` 同一天時沒有）、`來源：…`（事實，不帶推論字樣）；每列明細一行 `加入追蹤`（按鈕）或 `已在追蹤`（連到我的追蹤的計畫） | 新聞情緒分項後的 `推論`；理由文字自帶的 `（推論）`（不另加 badge，#661）；每列 AI 入口 `AI 推論 ▸`（有 `llm_note`）或 `AI 說明 ▸`；明細的 AI 進出點說明區標題列一個 `AI 推論` | `當日零候選`／`尚無候選清單` |
| 大盤頁：大盤概況 | `dashboard.market_overview` | 標題 `大盤概況` 下一行 `資料 <market_overview.trading_date>`（與 `D` 同一天時沒有，#661）；加權指數、櫃買指數、成交金額（億元）、漲跌家數；資料日同 `D`；「資料說明」內來源與 `成交金額範圍：…`；四格之下一條 `加權指數與季線（MA60）`（`market_overview.taiex_ma60`，#561）：`加權指數 <收盤>（<D/>）<在季線之上／在季線之下／與季線持平>（季線 <MA60>）` 與近 250 個交易日內最近 3 段在季線之上的區段（頁面檢查未涵蓋這條，靠前端測試與後端 API 測試） | — | `上市大盤資料未取得`／`上櫃大盤資料未取得`；`季線資料不足：…`／`季線無資料：…` |
| 大盤頁：指數總表 | `dashboard.market_overview.indexes` 的台股三列（頁面 #633、API #681 起都沒有美股） | 在 `大盤概況` 與 K 線卡之間，標題 `指數總表`（日期 badge 規則同大盤概況）；三列依序加權指數、櫃買指數、台指期近月，沒有分組標題；每列一行：名稱（台指期接 ` 合約 YYYY/MM`）、收盤（點，指數兩位小數、台指期整數）、漲跌、漲跌幅（換月日兩格都是 `換月`）、相對季線（`之上／之下／持平 季線 <ma60>`、`資料不足（n／60 日）`、`無資料：…`）、來源；#661 起沒有資料日欄，與 `D` 不同天或 `stale` 的列在名稱下一行寫 `資料 YYYY/MM/DD`（`stale` 接 ` 非最新`），所以該列是兩行：名稱、`資料 …<TAB>收盤<TAB>…`；來源句 `來源：加權指數 …` 只此一處，#666 起是該表「資料說明」的第一行（表頭之前，截圖展開）；「資料說明」內臺灣期貨交易所的顯名（#564） | — | 該列 `無資料：尚未收集`／`無資料：尚無已驗證的資料日`／`無資料：最近一次擷取失敗（<日期>）`，數值格 `—` |
| 大盤頁：共用 K 線圖 | `taiex-bars.json`（`market`）、`tpex-bars.json`（`market-tpex`）、`tx-bars.json`（`market-tx`） | 指數總表之後一張個股頁的 K 線卡（`StockBarsChart`），卡標題是選中列的 `<名稱>日線`（預設 `加權指數日線`），標題下一行 `資料 <data_as_of>`（與 `D` 同一天時沒有，#661）；工具列有區間按鈕（同個股頁；均線勾選仍在工具列，#656 只把個股頁的移到圖下） `1M`～`全部`（預設 `6M`，#600，見 [stocks.md 陷阱](stocks.md#陷阱)）；`最近 <count> 根日線；缺日不補、停牌不畫 K 線`；資料表最新一根（單位「點」，指數兩位小數、台指期整數）；台指期卡最後有開放資料顯名（#564；美股四檔 #633 起不能選） | — | `無資料`＋`來源未提供日線` |
| 熱門族群 | `today-board.json` | 榜別分頁下一行 `資料 <B/>`（與 `D` 同一天時沒有，#661）；每列 `資料 <B/> · 相對加權指數` | — | `meta.empty_message` 或 `此榜目前沒有族群` |

`D` = `dashboard.as_of` 前 10 字；`B` = `today-board.json` 的 `meta.trading_date`；`C` = `candidates.json` 的 `trading_date`。

## 檢查

| 編號 | 類型 | 檢查 | 怎麼判 |
| --- | --- | --- | --- |
| T1 | CI | 頁面可用 | `today`、`market` 兩張截圖兩個寬度與 `market-tpex`、`market-tx` 的 1280 都 `ready` true、`httpErrors` 與 `consoleErrors` 空、`overflow` false |
| T2 | CI | 導覽列資料日 | `today-1280.txt` 有整行 `資料 <D/>`，且 `D` 等於 `facts.json` 的 `market_latest_trading_date`。`D` 缺少時：`market_latest_trading_date` 非 null 判失敗（DB 有行情、頁面沒有資料日），兩邊都沒有才查整行 `資料日期未提供`。#661：`today-390.txt` 的第一個 `資料 ` 行也是 `資料 <D/>`（導覽列不收進手機選單），`today` 390 截圖 `overflow` false、`scrollWidth` 等於 `clientWidth`。`D` 的上游 |
| T3 | CI | 頁首資料列 | 沒有以 `資料截至 <D/>` 開頭的行（#661：導覽列已標 `D`）；整行 `今日`（頁首隱藏標題）的下一行以 ` · ` 分出來源與模式兩段且都非空；來源等於 `market.source_label`（null 時只要求非空）。`D` 的上游 |
| T4 | CI | 熱門族群日期 | `B` 不等於 `D` 時，整行 `熱門族群` 之後第一個 `資料 ` 開頭的行是 `資料 <B/>`；等於 `D` 時之後沒有 `資料 ` 開頭的行（#661）；`B` 等於 `facts.json` 的 `group_scores_latest_trading_date`。`B` 缺少時：`group_scores_latest_trading_date` 非 null 判失敗，兩邊都沒有才查整行 `資料日期未提供`。`B` 的上游 |
| T5 | CI | 熱門族群列 | 整行 `資料 <B/> · 相對加權指數` 的行數 = `min(5, items 數)`（今日頁各榜前 5）；`items[0].display_name` 為整行出現。`items` 空時：`facts.json` 的 `group_scores_latest_trading_date` 非 null 且等於該榜 `meta.trading_date`（或後者為 null），或 `dashboard-groups.json` 的 `groups` 有該日 `rank` 非 null 的族群，判失敗；都沒有才查空資料文案。`T` 的上游；`B` 用 T4 |
| T7 | CI | 今日名單日期、名次列與來源 | `status` 不是 `not_computed` 且 `items` 非空時：標題 `今日名單`（整行 `條件已成立 · 依評分排序` 之後的第一個整行 `今日名單`；導覽列也有一行 `今日名單`）的下一行是 `資料 <C/>`、再下一行 `<candidate_count> 檔`（#661：與頁面日期 `D` 同一天時這一行不能是 `資料 ` badge，不同天才要求這個 badge；`D` 讀不到時一律要求）；同天時下一行就是 `<candidate_count> 檔`；標題與 `熱門族群` 之間以 `#<n> <代號> ` 開頭的名次列（表格股票欄的第一行，#493；熱門族群列的 `#<n>` 自成一行，不算）依序等於 `items[].rank`（收合的其餘幾檔在截圖展開 `<details>` 後也列出）；`^來源：` 行數 = `items` 數，且 `C` 等於 `facts.json` 的 `candidate_run_latest_trading_date`。`items` 空時整行 `當日零候選`，`not_computed` 時整行 `尚無候選清單`；但 `facts.json` 的 `candidate_count_latest` > 0 且 `candidate_run_latest_trading_date` 等於 `candidates.json` 的 `trading_date`（或後者為 null）時判失敗 |
| T8 | CI | 今日名單推論標記 | 在 T7 之後（T7 沒通過時 T8 的失敗記「無法判定（上游 T7）」）。第 i 個 `^來源：` 行對應 `items[i]`（卡片依名次排列）；來源行都不含 `推論`（來源是事實，#661）；整行 `AI 推論` 的行數 = `items` 數（每個 AI 進出點說明區塊一個，#661）；沒有以 `（推論）` 結尾的行緊接一行 `推論`（推論理由不重複標，#661）；免責句 `由 AI 依上方規則數值、理由與關聯新聞撰寫的推論，不是買賣建議；價位以規則數值為準。` 的行數 = `items` 數；AI 入口 `AI 推論 ▸` 的個數 = `llm_note` 不為 null 的檔數，`AI 說明 ▸` 的個數 = 其餘檔數 |
| T9 | CI | 首頁只有一份名單 | 沒有整行 `關注標的`、`查看個股詳情 →`、`查看行動中心 →`、`明日候選`（#493：關注標的移到我的追蹤，持倉風險提示列連到 `查看我的追蹤 →`） |
| T10 | 人工 | 候選進出點說明 | 樣本：`candidates.json` 依名次前 3 檔（`manual/T10.json`）。每檔 `llm_note` 寫到的價位（進場、突破、拉回區間、停損、目標）都等於 `levels` 的對應值，進場方式與 `levels.entry_type` 一致，沒有 `levels` 以外的價位、保證或買賣指示；`llm_note` 未完成的那檔記無法判定。一檔不符即失敗，證據寫代號、說明原句與 `levels` 值 |
| T11 | CI | 大盤頁的大盤概況 | 讀 `market-1280.txt`（#549 起大盤概況在大盤頁）。整行 `大盤概況` 的下一行是 `資料 <market_overview.trading_date 換成 YYYY/MM/DD>`（日期為 null 時 `資料日期未提供`）（#661：與頁面日期 `D` 同一天時這一行不能是 `資料 ` badge，不同天才要求這個 badge；`D` 讀不到時一律要求）。`dashboard.market_overview` 每個交易所：`available` 時，`facts.json` 的 `market_summary_latest` 該交易所列的 `trading_date` 等於 `market_overview.trading_date`，且指數收盤、漲跌、成交金額、上漲與下跌家數與 API 相同；頁面有整行指數收盤（兩位小數、千分位；四捨五入同前端 `toFixed`，剛好 .5 時遠離零）、`<±漲跌>（<±漲跌幅>%）`、`<上市／上櫃> <成交金額÷1 億，兩位小數> <短範圍>`（`twse_all_securities` 為 `集中市場總計`、`tpex_stocks` 為 `上櫃股票`，其他值為 `scope_label`）、`<上市／上櫃> 上漲 n · 下跌 n · 平盤 n（漲停／跌停）`；「資料說明」有整行 `成交金額範圍：上市為<scope_label>；上櫃為<scope_label>`（只列 available 的交易所）。`unavailable` 時頁面有整行 `上市大盤資料未取得`／`上櫃大盤資料未取得`，但 `market_summary_latest` 該交易所列的日期等於 `market_overview.trading_date` 時判失敗 |
| T12 | CI | 區塊順序 | 標題 `今日名單`（同 T7 的定位）與整行 `熱門族群` 都在，且 `今日名單` 在前；沒有整行 `重點新聞`（首頁的新聞卡已移除，#625；PRODUCT_SPEC §2） |
| T13 | CI | 加入追蹤 | 在 T7 之後。截圖展開每列明細；`items` 非空時，整行 `加入追蹤` 與整行 `已在追蹤` 的行數合計 = `items` 數，`已在追蹤` 的行數 = `items[].open_plan_id` 非 null 的筆數；`items` 空時兩種行都不出現 |
| T14 | CI | 今日名單的大盤摘要列 | `today-1280.txt` 有相連的四行：`加權 <收盤，兩位小數> <±漲跌幅，兩位小數>%`（`change_pct` 為 null 時 `—`；`unavailable` 或收盤為 null 時整行 `加權 未取得`）、同格式的 `櫃買 …`、`資料 <market_overview.trading_date 換成 YYYY/MM/DD>`（null 時 `資料日期未提供`；與 `D` 同一天時沒有這一行，三行相連，#661）、`看大盤 →`；這幾行在標題 `今日名單`（同 T7 的定位）之前；頁面沒有整行 `漲跌家數（股票）`、`括號為漲停／跌停`（四格大盤概況已移到大盤頁） |
| T15 | CI | 大盤頁的共用日 K | 依序讀 `market-1280.txt`＋`taiex-bars.json`（預設）、`market-tpex-1280.txt`＋`tpex-bars.json`、`market-tx-1280.txt`＋`tx-bars.json`（`?index=` 選的列，#564）。每張截圖：有整行該列的圖標題（`加權指數日線`、`櫃買指數日線`、`台指期近月日線`），其他 6 檔的 `<名稱>日線` 都不出現（只有一張圖、網址選擇有效），標題在整行 `指數總表` 之後；台指期標題之後有整行 `資料來源：臺灣期貨交易所（政府資料開放平臺，政府資料開放授權條款第1版）`。API `bars` 非空時至少一根可畫（同前端 `isDrawableBar`：未停牌、開高低收都是正數且高、低包住開收；收盤-only 的列開＝高＝低＝收也算），標題的下一行是 `資料 <data_as_of 換成 YYYY/MM/DD>`（#661：與頁面日期 `D` 同一天時這一行不能是 `資料 ` badge，不同天才要求這個 badge；`D` 讀不到時一律要求），其後有整行 `最近 <count> 根日線；缺日不補、停牌不畫 K 線`，資料表（截圖展開）有一行以 `<最新一根可畫的日期 YYYY/MM/DD>`、tab、開、高、低、收（指數兩位小數、台指期整數，以 tab 分隔）開頭；`bars` 空時其後有整行 `來源未提供日線`。CI 假資料庫有三者的日線（台指期只有最後 10 個交易日、整數點，`fixture_data.TX_SESSIONS`） |
| T16 | CI | 大盤頁的指數總表 | 讀 `market-1280.txt` 與 `dashboard.json` 的 `market_overview.indexes` 中 `key` 為 `taiex`、`tpex`、`tx` 的三列（要依這個順序都在；#681 起 API 只回這三列）。整行 `指數總表` 在整行 `大盤概況` 之後、`加權指數日線` 之前。三列依序（儲存格以 tab 分隔；#661 起沒有資料日欄）：與 `D` 同一天且不是 `stale` 的列是一整行 `名稱<TAB>收盤…`，其餘的列是兩行：名稱，下一行 `資料 YYYY/MM/DD`（`stale` 接 ` 非最新`）`<TAB>收盤…`。名稱（台指期有 `contract_month` 時接 ` 合約 YYYY/MM`）、收盤（千分位，指數兩位小數、台指期整數）、漲跌（同位數、正數帶 `+`）、漲跌幅（兩位小數加 `%`、正數帶 `+`；`change_status=contract_roll` 時這兩格都是 `換月`；null 寫 `—`）、相對季線（`ma60.status=available` 時 `<之上／之下／持平> 季線 <ma60，同收盤位數>`；`insufficient` 時 `資料不足（<close_count>／<required_closes> 日）`；`unavailable` 時 `無資料：日線未收集`／`無資料：日線最新為 <日期>`／`無資料：季線尚未計算`，其他 `無資料`）、`source.label`；`unavailable` 的列是兩行 `<名稱>`、`<原因>\t—\t—\t—\t—\t<來源>`，原因 `無資料：尚未收集`、`no_verified_session` 為 `無資料：尚無已驗證的資料日`、`fetch_failed` 為 `無資料：最近一次擷取失敗（<last_attempt_date>）`。表頭沒有 `資料日`；整行來源句 `來源：加權指數 臺灣證券交易所；櫃買指數 證券櫃檯買賣中心；台指期近月 臺灣期貨交易所` 恰一行（#661），且在 `指數總表` 之後、表頭 `指數<TAB>…` 之前（#666 起在該表的「資料說明」裡，不在表下）。`指數總表` 之後有整行臺灣期貨交易所顯名（資料說明，截圖展開）。頁面沒有美股的內容（#633）：沒有整行 `美股`、`美股（前一交易日）`、`資料來源：FinMind（個人非商業使用）`，也沒有以 `S&P 500`、`NASDAQ 綜合指數`、`道瓊工業指數`、`費城半導體指數` 開頭的表格列 |
| T17 | CI | 手機候選列數字區 | 讀 `today-390` 截圖 JSON 的 `candidateRows`（`screenshot.cjs` 在展開所有 `<details>` 後量每個顯示中的 `.candidate-row`，含其餘幾檔；#608）。量到的名次依序等於 `items[].rank`（`not_computed` 或 `items` 空時沒有列）；每列 `.candidate-row-nums` 的 `scrollWidth ≤ clientWidth`、`covered` 空（收盤、RR、總分的 `dt`／`dd` 都不與 `.candidate-ai-toggle` 重疊）、`clipped` 空（沒有 `dt`／`dd` 超出列的左右邊；外框 `overflow: hidden` 會靜默切掉，頁面不會橫向捲動，T1 抓不到） |
| T18 | CI | 今日名單走勢線的收盤 | 讀 `candidates.json`（#653）。`not_computed` 或 `items` 空時沒有列。每個 item 都有 `recent_closes`；`dates` 與 `closes` 等長、不超過 30 個交易日、日期由舊到新不重複、最後一日不晚於 `trading_date`；`closes` 每個值是正數或 null（缺日留空，不補值）；最後一日等於 `trading_date` 時，該日收盤等於 `market.close`（同一筆已存日線，與個股頁 K 線同來源）。線本身（漲紅跌綠、`aria-label`、不帶文字、不到 2 個收盤不畫）由前端測試鎖住，頁面文字看不到 SVG，所以這裡只驗它畫的資料 |
| T19 | CI | 分數橫條與漲跌文字（#654、#675） | 讀 `today-1280` 截圖 JSON 的 `graphics`（`screenshot.cjs` 展開所有 `<details>` 後量每個 `.score-bar`、`.strength-chip`）。分數橫條依序是每檔候選（`candidates.json` 的 `items`）的技術、籌碼、新聞情緒、族群四條：`aria-label` 為 `<分項> <round(score×100)>（0–100）`、`data-score` 同值，填色寬度÷底軌寬度與 `score` 差不超過 0.02；`score` 為 null 時 `aria-label` 為 `<分項> 無資料`、沒有填色。漲跌文字依序是 `today-board.json` 前 5 名各三個（1／5／20 日）：`aria-label` `<N> 日相對加權指數 <±N.NN%>`、文字與 `data-strength`（`up`／`down`／`flat`／`none`）由 `relative_returns` 算出；每個 `.strength-chip` 的 `::before` 底色都要是透明（alpha 0）或不透明度 0，有底色就失敗（#675 拿掉 #654 的色塊；文字顏色由前端測試鎖住） |
| T20 | CI | 窄版點列開圖（#665） | 讀 `candidates.json`；`not_computed` 或 `items` 空時沒有可開的卡（通過）。`today-390.txt`（初次載入，截圖展開所有 `<details>` 也一樣）沒有任何候選的整行 `<代號> <名稱>`（K 線卡標題）與 `規則價位線：` 開頭的行。`today-chart` 截圖（390，`--click '.candidate-row[data-candidate-rank="1"] .candidate-chart-toggle'`）：點擊有找到元素（`missingClicks` 空；#665 前名次是 `aria-pressed` 的選圖按鈕，沒有這個 class，所以改前失敗）、不橫向捲動、沒有 `consoleErrors`；第一個候選列行以 `#<rank> <代號> <名稱> ` 開頭，整行 `<代號> <名稱>` 恰一行且在這一列與下一列（只有一列時是 `熱門族群`）之間，其後、下一列之前有 `規則價位線：` 開頭的行（含規則價位線）；其他候選的 `<代號> <名稱>` 都不出現（一次一檔）。初次載入不掛載卡、不發 `/bars`、不在寬度 0 的容器初始化 ECharts 由前端測試（`candidates.test.tsx` 的 Issue 665 段）鎖住，頁面文字看不到 |
| T21 | CI | 寬版明細不並排擠壓（#668） | 讀 `today-1280` 與 `today-wide`（1440，只有這一張）截圖 JSON 的 `candidateDetails`（`screenshot.cjs` 展開所有 `<details>` 後量每個顯示中的列的 `.candidate-detail[open]`）。量到的名次依序等於 `items[].rank`（`not_computed` 或 `items` 空時沒有列）；每個明細「AI 進出點說明」內文（第一段的 `dd`，未完成時是那一句說明）的寬度 ÷ 字級 ≥ `NOTE_MIN_CHARS`（20 字）；`AI 推論` badge 存在，且與明細內其他葉元素（不含 badge 自己的文字）的框不相交（`badgeOverlaps` 空）。量測是 `null`（量測丟例外，#609）或沒有這個欄位時無法判定。#668 前 1280 與 1440 的說明內文只有 24px（約 1.5 字），badge 疊在「目標一／二」上，所以改前失敗；innerText 不隨欄寬改變，T7 等文字檢查看不到 |
| T22 | CI | 隔夜美股與費半（#681） | 讀 `candidates.json` 的 `overnight_us` 與 `today-1280.txt`。`overnight_us.indexes` 依序是 `SPX`、`IXIC`、`DJI`、`SOX`（沒有 `overnight_us` 就失敗：#681 前的 API 沒有這欄，所以改前失敗）。以 `隔夜美股` 開頭的行恰一行，在標題 `今日名單`（同 T7 的定位）之後、`熱門族群` 之前（有名單、零候選、尚無清單都有），內容照前端 `overnightUsView`：`隔夜美股`，四檔都不是 `latest`／`us_market_closed`（含都沒有收盤）時接 ` 美股尚未更新`，有新資料而全是 `us_market_closed` 時接 ` 美股休市`；有收盤的幾檔同一天時接 ` 資料 <YYYY/MM/DD>`；再接四段以 ` · ` 分隔的 `<S&P 500／NASDAQ／道瓊／費半> <漲跌幅>`（`change_pct`×100 兩位小數、正數帶 `+`，null 為 `—`，沒有收盤為 `未取得`；日期不同時每段接 `（YYYY/MM/DD）`；不是「美股尚未更新」時 `stale` 的那段接 ` 非最新`），都沒有收盤時只有前兩段。每個 item 都有 `overnight_us_links`；有連結且該檔有收盤時，以 `#<rank> <代號> ` 開頭的名次列以 `#<rank> <代號> <名稱> 費半 <漲跌幅> ` 開頭（不是 `latest`／`us_market_closed` 時漲跌幅後再接 ` 非最新`；在市場與族群之前，行尾省略號截不到它），沒有連結的列不出現美股。對應族群（`app.domain.US_INDEX_GROUP_LINKS`）與漲跌顏色由後端與前端測試鎖住 |

## 陷阱

- 候選在 1280 是表格（640px 以下改卡片，1280 的頁面文字沒有卡片）：一列的儲存格以 tab 分隔，股票欄在行首，第一行是 `#<名次> <代號> <名稱>`（#493）；明細列在 `<details>` 裡，截圖展開後才有 `來源：`、AI 說明區與免責句（#276）。熱門族群列也有 `#<n>`，所以名次列只數 `今日名單` 與 `熱門族群` 之間。
- `dashboard.as_of` 帶時間，`D` 只取前 10 字。`D` 本身是 API 的 `-` 分隔日期，頁面上的 badge 一律是 `/` 分隔：導覽列 `資料 <D/>`、各卡片 `資料 <B/>`、`資料 <C/>` 等（UI_COPY_SPEC §1，#270）。
- 頁面日期只標一處（#661，[DESIGN_SYSTEM §7](../../../../docs/DESIGN_SYSTEM.md#7-資料與狀態的視覺語言)）：導覽列的 `資料 <D/>` 是每頁唯一的日期；卡片 badge、列上的 `資料 …`、句子裡的日期與 `D` 同一天就不出現。檢查以 `page_checks.card_badge` 判：同天時那一行不能是 `資料 ` badge，不同天時必須是。假資料庫各處日期都等於 `D`，所以 CI 主要驗「同天不標」；「不同天仍標」由我的追蹤 A15（計畫卡較早的模擬日）與前端測試（研究截止日、財務卡季別、台指期晚一天）鎖住。
- 分數橫條（#654）與漲跌文字（#675，[DESIGN_SYSTEM §5](../../../../docs/DESIGN_SYSTEM.md#5-元件)）保留數字：明細「分項分數與理由」的四分項在頁面文字仍是 `<分項>` 一行、`<0–100 整數或 —>` 一行；熱門族群第二行仍是 `1 日 <±%> 5 日 <±%> 20 日 <±%>`（漲跌文字是 `<b>`，文字不變）。填色比例與「沒有底色」只能從 `graphics` 量測看到，由 T19 檢查。

## 判定

- 通過：T1～T9、T11～T22 全部通過；T10 由人工判讀另記。
- 失敗：任一條失敗，列出編號、預期與實際。
- 無法判定：沒有失敗，但有檢查無法判定（API 非 200、截圖未 ready，或上游沒通過，見 [README 三態與上游](README.md#三態與上游)）；列出 URL 或上游編號。

## 輸出格式

```markdown
### 今日名單 `/`：失敗

| 檢查 | 結果 | 原因類別 | 證據 |
| --- | --- | --- | --- |
| T1 | 通過 | — | 1280／390 ready，無錯誤，無橫向捲動 |
| T2 | 通過 | — | `資料 2099-01-02` = facts 2099-01-02 |
| T4 | 失敗 | 產品缺陷 | `熱門族群` 後第一個資料行是 `資料 2099/01/01`，預期 `資料 2099/01/02`（today-1280.txt 第 58 行） |

截圖：shots/today-1280.png、shots/today-390.png
```

記下供後續檔案使用：`B`、`today-board.json` 的 `items[0].theme_id` 與 `display_name`（族群路徑的起點）。
