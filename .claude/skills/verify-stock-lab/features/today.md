# 今日 `/`

入口：主導航「今日」（`MAIN_NAV` 第一項），`TodayPage`（`frontend/src/App.tsx`）；`MAIN_NAV` 在 `frontend/src/components/Navbar.tsx`。

## API

| 檔名 | URL（前綴 `<API>/api`，`<API>` 為 API 的 origin） |
| --- | --- |
| `dashboard.json` | `/dashboard` |
| `today-board.json` | `/themes?board=industry&limit=5` |
| `candidates.json` | `/candidates` |
| `news-<id>.json` | `/news/<id>`，`dashboard.json` 的 `news` 前 3 則各一個 |

## 驗證範圍

改到下列前端檔或 API route 時，CI 驗這一頁；規則見 [README 驗證範圍](README.md#驗證範圍)。

| 種類 | 對象 |
| --- | --- |
| 前端檔 | `frontend/src/candidates/CandidateViews.tsx` |
| 前端檔 | `frontend/src/today/TodayViews.tsx` |
| 前端檔 | `frontend/src/news/NewsViews.tsx` |
| 前端檔 | `frontend/src/themes/ThemeViews.tsx` |
| 前端檔 | `frontend/src/actions/actionTiers.ts` |
| API route | `GET /dashboard` |
| API route | `GET /themes` |
| API route | `GET /candidates` |
| API route | `GET /news/{news_id}` |

## 截圖

`--url <WEB>/ --name today`（1280 與 390）。

## 預期資料與標記

| 區塊 | 資料來源 | 必須顯示的來源與資料日期 | 「推論」位置 | 空資料文案 |
| --- | --- | --- | --- | --- |
| 導覽列 | `dashboard.as_of` | `資料 <D/>`（右上 badge） | — | `資料日期待核實` |
| 頁首資料列 | `dashboard.as_of`、`market.source_label`、`mode` | 一行 `資料截至 <D/> · <來源> · <模式>`；「資料說明」內 `成交金額範圍：…` | — | 模式 `尚無官方快照` |
| 大盤概況 | `dashboard.market_overview` | 加權指數、櫃買指數、成交金額（億元）、漲跌家數；資料日同 `D` | — | `上市大盤資料未取得`／`上櫃大盤資料未取得` |
| 持倉風險提示列 | `dashboard.actions` 的持倉風險 | — | — | 沒有持倉風險時不出現 |
| 明日候選 | `candidates.json` | 標題下 `資料 <C/>` 與 `<n> 檔`；每列 `#<名次>`；每列明細 `資料日期 <C/>`、`來源：…` | 新聞情緒分項與理由後的 `推論`；每列 AI 入口 `AI 推論 ▸`（有 `llm_note`）或 `AI 說明 ▸`；明細的 `AI 推論` 說明區；來源行結尾 `（推論）` | `當日零候選`／`尚無候選清單` |
| 熱門族群 | `today-board.json` | 榜別分頁下一行 `資料 <B/>`；每列 `資料 <B/> · 相對加權指數` | — | `meta.empty_message` 或 `此榜目前沒有族群` |
| 重點新聞 | `dashboard.news` 前 3 則 | 每則：來源 badge、`發布於／事件於／事件日 …` 時間 | 有 AI 判讀的卡在方向後接 `AI 推論` | `市場新聞區尚無可顯示內容。` |
| 關注標的 | `dashboard.actions` ＋ `dashboard.candidates` | 每張卡 `資料日 YYYY/MM/DD` | — | `dashboard.empty_states.actions` 或 `目前沒有可顯示的行動摘要。` |

`D` = `dashboard.as_of` 前 10 字；`B` = `today-board.json` 的 `meta.trading_date`；`C` = `candidates.json` 的 `trading_date`。

## 檢查

| 編號 | 類型 | 檢查 | 怎麼判 |
| --- | --- | --- | --- |
| T1 | CI | 頁面可用 | 兩個寬度 `ready` true、`httpErrors` 與 `consoleErrors` 空、`overflow` false |
| T2 | CI | 導覽列資料日 | `today-1280.txt` 有整行 `資料 <D/>`，且 `D` 等於 `facts.json` 的 `market_latest_trading_date`。`D` 缺少時：`market_latest_trading_date` 非 null 判失敗（DB 有行情、頁面沒有資料日），兩邊都沒有才查整行 `資料日期待核實`。`D` 的上游 |
| T3 | CI | 頁首資料列 | 第一個 `資料截至 ` 開頭的行以 `資料截至 <D/> · ` 開頭，其後以 ` · ` 分出來源與模式兩段且都非空；來源等於 `market.source_label`（null 時只要求非空）。`D` 的上游 |
| T4 | CI | 熱門族群日期 | 整行 `熱門族群` 之後第一個 `資料 ` 開頭的行是 `資料 <B/>`；`B` 等於 `facts.json` 的 `group_scores_latest_trading_date`。`B` 缺少時：`group_scores_latest_trading_date` 非 null 判失敗，兩邊都沒有才查整行 `資料日期待核實`。`B` 的上游 |
| T5 | CI | 熱門族群列 | 整行 `資料 <B/> · 相對加權指數` 的行數 = `min(5, items 數)`（今日頁各榜前 5）；`items[0].display_name` 為整行出現。`items` 空時：`facts.json` 的 `group_scores_latest_trading_date` 非 null 且等於該榜 `meta.trading_date`（或後者為 null），或 `dashboard.json` 的 `groups` 有該日 `rank` 非 null 的族群，判失敗；都沒有才查空資料文案。`T` 的上游；`B` 用 T4 |
| T6 | CI | 新聞卡與 AI 標記 | `dashboard.news` 前 3 則的標題（`title`）各為整行出現；其中 `news-<id>.json` 的 `ai.status` 為 `done` 且 `ai.inference` 為 true 的：`dashboard.news` 該則的 `ai` 與它相同，卡片有整行 `AI 推論`，其上一行（方向行）等於 AI 方向（`ai.unsupported` 為 true 時是 `影響尚未判定`，否則 `ai.impact_direction` 照 positive／negative／mixed 寫 `可能正向`／`可能負向`／`正負互見`，其餘 `影響尚未判定`；與新聞頁同一套，#233）。一張卡的範圍是它的標題行到下一則標題行之前；最後一則到其後的 `關注標的` 之前 |
| T7 | CI | 明日候選日期、名次列與來源 | `status` 不是 `not_computed` 且 `items` 非空時：整行 `明日候選` 的下一行是 `資料 <C/>`、再下一行 `<candidate_count> 檔`；`明日候選` 與 `熱門族群` 之間以 `#<n>` 加 tab 開頭的名次列（表格列；改版前的卡片是整行 `#<n>`，不算）依序等於 `items[].rank`（收合的其餘幾檔在截圖展開 `<details>` 後也列出）；`^來源：` 行數 = `items` 數，且 `C` 等於 `facts.json` 的 `candidate_run_latest_trading_date`。`items` 空時整行 `當日零候選`，`not_computed` 時整行 `尚無候選清單`；但 `facts.json` 的 `candidate_count_latest` > 0 且 `candidate_run_latest_trading_date` 等於 `candidates.json` 的 `trading_date`（或後者為 null）時判失敗 |
| T8 | CI | 明日候選推論標記 | 在 T7 之後（T7 沒通過時 T8 的失敗記「無法判定（上游 T7）」）。第 i 個 `^來源：` 行對應 `items[i]`（卡片依名次排列）；`components.news_sentiment.inference` 為 true 的候選，其來源行結尾為 `（推論）`；說明區標題 `AI 推論` 的整行數 ≥ `items` 數；免責句 `由 AI 依上方規則數值、理由與關聯新聞撰寫的推論，不是買賣建議；價位以規則數值為準。` 的行數 = `items` 數；AI 入口 `AI 推論 ▸` 的個數 = `llm_note` 不為 null 的檔數，`AI 說明 ▸` 的個數 = 其餘檔數 |
| T9 | CI | 關注標的 | `查看個股詳情 →` 的行數 k > 0 時，`^資料日 [0-9]{4}/[0-9]{2}/[0-9]{2}$` 的行數也 = k。k = 0 時：`dashboard.json` 的 `actions`＋`candidates` 有頁面會顯示的項目（同 `TodayPage` 的 `homeActions`：`action_state` 不是 `data_insufficient`，或 `held` 為 true，或 `position_quantity_status` 為 `unknown`），或 `candidates.json` 有 `items` 且 `trading_date` 等於 `facts.json` 的 `market_latest_trading_date`，判失敗；都沒有才查空資料文案整行出現 |
| T10 | 人工 | 候選進出點說明 | 樣本：`candidates.json` 依名次前 3 檔（`manual/T10.json`）。每檔 `llm_note` 寫到的價位（進場、突破、拉回區間、停損、目標）都等於 `levels` 的對應值，進場方式與 `levels.entry_type` 一致，沒有 `levels` 以外的價位、保證或買賣指示；`llm_note` 未完成的那檔記無法判定。一檔不符即失敗，證據寫代號、說明原句與 `levels` 值 |
| T11 | CI | 大盤概況 | `dashboard.market_overview` 每個交易所：`available` 時，`facts.json` 的 `market_summary_latest` 該交易所列的 `trading_date` 等於 `market_overview.trading_date`，且指數收盤、漲跌、成交金額、上漲與下跌家數與 API 相同；頁面有整行指數收盤（兩位小數、千分位；四捨五入同前端 `toFixed`，剛好 .5 時遠離零）、`<±漲跌>（<±漲跌幅>%）`、`<上市／上櫃> <成交金額÷1 億，兩位小數> <短範圍>`（`twse_all_securities` 為 `集中市場總計`、`tpex_stocks` 為 `上櫃股票`，其他值為 `scope_label`）、`<上市／上櫃> 上漲 n · 下跌 n · 平盤 n（漲停／跌停）`；「資料說明」有整行 `成交金額範圍：上市為<scope_label>；上櫃為<scope_label>`（只列 available 的交易所）。`unavailable` 時頁面有整行 `上市大盤資料未取得`／`上櫃大盤資料未取得`，但 `market_summary_latest` 該交易所列的日期等於 `market_overview.trading_date` 時判失敗 |
| T12 | CI | 區塊順序 | 整行 `明日候選`、`熱門族群`、`重點新聞` 都在，且 `明日候選` 在另兩行之前（PRODUCT_SPEC §2） |

## 陷阱

- 「有 AI 判讀」的定義見 [news.md 陷阱](news.md#陷阱)（T6）。
- 候選在 1280 是表格（640px 以下改卡片，1280 的頁面文字沒有卡片）：一列的儲存格以 tab 分隔，名次格在行首；明細列在 `<details>` 裡，截圖展開後才有 `來源：`、AI 說明區與免責句（#276）。熱門族群列也有 `#<n>`，所以名次列只數 `明日候選` 與 `熱門族群` 之間。
- `dashboard.as_of` 帶時間，`D` 只取前 10 字。`D` 本身是 API 的 `-` 分隔日期，頁面上的 badge 一律是 `/` 分隔：導覽列 `資料 <D/>`、各卡片 `資料 <B/>`、`資料 <C/>` 等（UI_COPY_SPEC §1，#270）。

## 判定

- 通過：T1～T9、T11、T12 全部通過；T10 由人工判讀另記。
- 失敗：任一條失敗，列出編號、預期與實際。
- 無法判定：沒有失敗，但有檢查無法判定（API 非 200、截圖未 ready，或上游沒通過，見 [README 三態與上游](README.md#三態與上游)）；列出 URL 或上游編號。

## 輸出格式

```markdown
### 今日 `/`：失敗

| 檢查 | 結果 | 原因類別 | 證據 |
| --- | --- | --- | --- |
| T1 | 通過 | — | 1280／390 ready，無錯誤，無橫向捲動 |
| T2 | 通過 | — | `資料 2099-01-02` = facts 2099-01-02 |
| T4 | 失敗 | 產品缺陷 | `熱門族群` 後第一個資料行是 `資料 2099/01/01`，預期 `資料 2099/01/02`（today-1280.txt 第 58 行） |

截圖：shots/today-1280.png、shots/today-390.png
```

記下供後續檔案使用：`B`、`today-board.json` 的 `items[0].theme_id` 與 `display_name`（族群路徑的起點）。
