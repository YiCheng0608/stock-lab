# 今日 `/`

入口：主導航「今日」（`MAIN_NAV` 第一項），`TodayPage`（`frontend/src/App.tsx`）。

## API

| 檔名 | URL（前綴 `http://127.0.0.1:8227/api`） |
| --- | --- |
| `dashboard.json` | `/dashboard` |
| `today-board.json` | `/themes?board=industry&limit=10` |
| `candidates.json` | `/candidates` |
| `news-<id>.json` | `/news/<id>`，`dashboard.json` 的 `news` 前 3 則各一個 |

## 截圖

`--url http://127.0.0.1:4227/ --name today`（1280 與 390）。

## 預期資料與標記

| 區塊 | 資料來源 | 必須顯示的來源與資料日期 | 「推論」位置 | 空資料文案 |
| --- | --- | --- | --- | --- |
| 導覽列 | `dashboard.as_of` | `資料 <D>`（右上 badge） | — | `資料日期待核實` |
| 資料截至卡 | `dashboard.as_of`、`market.source_label` | `資料截至` 下一行 `<D/>`，再下一行來源名稱 | — | `尚無官方快照` |
| 今日市場／重大事件 | `dashboard.news` 前 3 則 | 每張卡：來源 badge、`發布於／事件於／事件日 …` 時間 | 有 AI 判讀的卡在方向後接 `AI 推論` | `市場新聞區尚無可顯示內容。` |
| 熱門族群 | `today-board.json` | 榜別分頁下一行 `資料 <B/>`；每張卡 `資料 <B/> · 相對加權指數` | — | `meta.empty_message` 或 `此榜目前沒有族群` |
| 明日候選 | `candidates.json` | 標題下 `資料 <C/>` 與 `<n> 檔`；每張卡 `資料日期 <C/>`、`來源：…` | 新聞情緒分項與理由後的 `推論`；每張卡的 `AI 推論` 說明區；來源行結尾 `（推論）` | `當日零候選`／`尚無候選清單` |
| 關注標的 | `dashboard.actions` ＋ `dashboard.candidates` | 每張卡 `資料日 YYYY/MM/DD` | — | `dashboard.empty_states.actions` 或 `目前沒有可顯示的行動摘要。` |

`D` = `dashboard.as_of` 前 10 字；`B` = `today-board.json` 的 `meta.trading_date`；`C` = `candidates.json` 的 `trading_date`。

## 檢查

| 編號 | 檢查 | 怎麼判 |
| --- | --- | --- |
| T1 | 頁面可用 | 兩個寬度 `ready` true、`httpErrors` 與 `consoleErrors` 空、`overflow` false |
| T2 | 導覽列資料日 | `today-1280.txt` 有整行 `資料 <D>`，且 `D` 等於 `facts.json` 的 `market_latest_trading_date` |
| T3 | 資料截至卡 | 整行 `資料截至` 的下一行是 `<D/>`，再下一行非空且等於 `market.source_label`（null 時只要求非空） |
| T4 | 熱門族群日期 | 整行 `熱門族群` 之後第一個 `資料 ` 開頭的行是 `資料 <B/>`；`B` 等於 `facts.json` 的 `group_scores_latest_trading_date` |
| T5 | 熱門族群卡 | 整行 `資料 <B/> · 相對加權指數` 的行數 = `min(10, items 數)`；`items[0].display_name` 為整行出現。`items` 空時改查空資料文案 |
| T6 | 新聞卡與 AI 標記 | `dashboard.news` 前 3 則的標題（`title`）各為整行出現；其中 `news-<id>.json` 的 `ai.status` 為 `done` 且 `ai.inference` 為 true 的，卡片方向行之後要有整行 `AI 推論`（以標題行到下一張卡之間的文字判斷）；有 AI 判讀卻顯示 `影響尚未判定` 為失敗 |
| T7 | 明日候選日期與來源 | `status` 為清單時：整行 `明日候選` 的下一行是 `資料 <C/>`、再下一行 `<candidate_count> 檔`；`^來源：` 行數 = `items` 數，且 `C` 等於 `facts.json` 的 `candidate_run_latest_trading_date` |
| T8 | 明日候選推論標記 | 每個 `components.news_sentiment.inference` 為 true 的候選，其來源行結尾為 `（推論）`；說明區標題 `AI 推論` 的整行數 ≥ `items` 數；免責句 `由 AI 依上方規則數值、理由與關聯新聞撰寫的推論，不是買賣建議；價位以規則數值為準。` 的行數 = `items` 數 |
| T9 | 關注標的 | `查看個股詳情 →` 的行數 k > 0 時，`^資料日 [0-9]{4}/[0-9]{2}/[0-9]{2}$` 的行數也 = k；k = 0 時空資料文案為整行出現 |

## 判定

- 通過：T1～T9 全部通過。
- 失敗：任一條失敗，列出編號、預期與實際。
- 無法判定：T1 的 `ready` 為 false，或任一 API 非 200；依賴它的檢查不判，列出 URL。

## 輸出格式

```markdown
### 今日 `/`：失敗

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| T1 | 通過 | 1280／390 ready，無錯誤，無橫向捲動 |
| T2 | 通過 | `資料 2026-10-21` = facts 2026-10-21 |
| T6 | 失敗 | 第 3 則「台股反彈594點…」`/api/news/1946` 有 AI 判讀（done），今日卡顯示 `影響尚未判定`、無 `AI 推論` |

截圖：shots/today-1280.png、shots/today-390.png
```

記下供後續檔案使用：`B`、`today-board.json` 的 `items[0].theme_id` 與 `display_name`（族群路徑的起點）。
