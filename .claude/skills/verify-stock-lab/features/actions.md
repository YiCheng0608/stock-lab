# 行動 `/actions`

入口：主導航「行動」，`ActionsPage`（行動中心，`frontend/src/App.tsx`；列表在 `frontend/src/actions/`）。列表依 `action_tier_v1` 分級（[UI_COPY_SPEC §5](../../../../docs/UI_COPY_SPEC.md#5-行動中心的分級與預設篩選)）。`/actions/:exchange/:symbol` 轉到 `/stocks/:exchange/:symbol?tab=research`。路徑：個股檔的 `E`、`S`（[README 選股](README.md#選股)）→ 行動詳情（轉址後的個股研究條件分頁）。

## API

| 檔名 | URL（前綴 `<API>/api`，`<API>` 為 API 的 origin） |
| --- | --- |
| `actions.json` | `/actions?limit=20`（預設篩選：`view=focus`、不含 ETF） |
| `actions-tier<n>.json` | `/actions?tier=<n>&limit=5`：`actions.json` 的 `summary.tiers` 中 `shown` > 0、但 `items` 沒有該級列的每一級（頁面首屏另外載入的前 5 列） |
| `actions-holdings.json` | `/actions?tier=0&limit=100`（全部持倉，A8 用） |
| `portfolio.json` | `/portfolio?page=1&page_size=20` |
| `action-detail.json` | `/actions/<E>/<S>` |

## 驗證範圍

改到下列前端檔或 API route 時，CI 驗這一頁；規則見 [README 驗證範圍](README.md#驗證範圍)。

| 種類 | 對象 |
| --- | --- |
| 前端檔 | `frontend/src/candidates/CandidateViews.tsx` |
| 前端檔 | `frontend/src/actions/ActionViews.tsx` |
| 前端檔 | `frontend/src/actions/actionTiers.ts` |
| 前端檔 | `frontend/src/news/NewsViews.tsx` |
| 前端檔 | `frontend/src/stock/StockBarsChart.tsx` |
| 前端檔 | `frontend/src/stock/StockHeader.tsx` |
| 前端檔 | `frontend/src/stock/StrategyBoardPanel.tsx` |
| 前端檔 | `frontend/src/stock/strategyBoard.ts` |
| 前端檔 | `frontend/src/stock/stockTabs.ts` |
| API route | `GET /dashboard` |
| API route | `GET /actions` |
| API route | `GET /actions/{exchange}/{symbol}` |
| API route | `GET /portfolio` |
| API route | `GET /stocks/{exchange}/{symbol}` |
| API route | `GET /stocks/{exchange}/{symbol}/bars` |
| API route | `GET /news` |

## 截圖

| 名稱 | 參數 |
| --- | --- |
| `actions` | `--url <WEB>/actions --name actions`（1280 與 390） |
| `action-detail` | `--url <WEB>/actions/<E>/<S> --name action-detail --widths 1280`（不點分頁：轉址後應已在研究條件分頁） |

## 預期資料與標記

| 區塊 | 資料來源 | 必須顯示的來源與資料日期 | 「推論」位置 | 空資料文案 |
| --- | --- | --- | --- | --- |
| 我的庫存 | `portfolio.json` | 每筆 `記錄來源 … · 記錄日期 …`（本地記錄，標「來源／日期待核實」） | — | `尚未建立庫存。` |
| 篩選與隱藏句 | `actions.json` 的 `summary` | — | — | `summary.hidden` 都是 0 時沒有隱藏句 |
| 各級區塊與列 | `actions.json` 的 `items`、`summary.tiers` | 每列的 `資料日` 格 `YYYY/MM/DD` | 本頁沒有 LLM 產出，不應出現 `推論` | `目前沒有符合篩選的標的。` |
| 行動詳情（轉址後的研究條件分頁） | `action-detail.json` 的 `decision_summary` | `資料日期：…`、`資料日：… · 價位語意：…` | 同個股 S5 | `尚無行動摘要。` |

## 檢查

| 編號 | 類型 | 檢查 | 怎麼判 |
| --- | --- | --- | --- |
| A1 | CI | 頁面可用 | 每張截圖 `ready` true、`missingClicks` 空、`httpErrors` 與 `consoleErrors` 空、`overflow` false |
| A2 | CI | 庫存區 | `actions-1280.txt` 有整行 `我的庫存`；`portfolio.json` 的 `items` 空時有整行 `尚未建立庫存。`，否則 `記錄來源 ` 開頭的行數 = `items` 數 |
| A3 | CI | 各級區塊與分頁文字 | `summary.tiers` 中 `shown` > 0 的每一級：有整行 `第 <tier> 級`，下一行是 `label`，再下一行是 `顯示 <k>／<shown 千分位> 檔`（k 是頁面載入的該級列數：`actions.json` 的 `items` 有該級列時是那些列，沒有時是 `actions-tier<n>.json` 的列數）；`shown` > k 時區塊內有 `顯示更多（還有 <shown − k> 檔）`。`shown` 為 0 的級別沒有區塊；都沒有時有整行 `目前沒有符合篩選的標的。` |
| A4 | CI | 每列資料日 | 以 `<TAB>YYYY/MM/DD<TAB>策略總表 →` 結尾的行（表格每列的資料日格與連結格）數 k = 頁面載入的列數（`actions.json` 的 `items` 加上各 `actions-tier<n>.json` 的 `items`），列數非空時 k > 0（API 有資料、頁面沒有列判失敗）；這些日期都等於 `meta.data_as_of` 的 `YYYY/MM/DD` 或更早，且 `meta.data_as_of` 等於 `facts.json` 的 `market_latest_trading_date` |
| A5 | CI | 沒有未標示的推論 | `actions-1280.txt` 不含 `AI 推論` 與 `（推論）` 兩個字串（`grep -F`；本頁不放 LLM 產出；出現就判失敗並記行號）。頁面沒有任何行動列（A4 的 k = 0）時判無法判定，不判通過：沒有內容可查 |
| A6 | CI | 轉址後的研究條件分頁 | 截圖不點分頁；`action-detail-1280.txt` 有整行 `<S>` 與 `研究動作`（只在研究條件分頁出現，證明 `/actions/<E>/<S>` 落在 `?tab=research`）；`decision_summary` 非 null 時有 `資料日：` 開頭的行，其日期等於 `decision_summary.data_cutoff` 的 `YYYY/MM/DD`（前 10 字）；null 時有 `尚無行動摘要。` |
| A7 | CI | 路徑一致 | 轉址後的 `action-detail` 頁首代號與名稱等於個股頁（`stock.json` 的 `instrument.symbol`、`name`） |
| A8 | CI | 今日候選 | `第 1 級`／`今日候選` 區塊內 `#<n><TAB>` 開頭的名次列依序等於頁面載入的第 1 級各列的 `candidate.rank`；`candidates.json` 的 `trading_date` 等於 `meta.data_as_of` 且第 1 級已全部載入（`shown` = 第 1 級列數）時，名次列等於 `candidates.json` 的 `items[].rank` 去掉持倉中的候選（`actions-holdings.json` 的標的歸第 0 級），列數等於 `candidate_count` 減去持倉中的候選數；持倉占掉第一頁時，名次列是它的前段；`trading_date` 不同日時不該有今日候選列 |
| A9 | CI | 預設清單沒有 ETF | `actions.json` 的 `summary.view` 為 `focus`、`include_etf` 為 false；頁面載入的列中，ETF 都是持倉（`tier` 0）或自選；頁面 `上市 · ETF`（或 `上櫃`、`市場待核實`）開頭的列數等於這些 ETF 數 |
| A10 | CI | 頁首隱藏數 | 有整行 `預設隱藏：ETF <etf> 檔、其他觀察 <observation> 檔、策略判斷資料待補 <data_insufficient> 檔；自選標的一律顯示。隱藏不刪資料，切換上方篩選即可看到。`（數字取自 `summary.hidden`，千分位，為 0 的項目不寫）；三項都是 0 時沒有 `預設隱藏：` 開頭的行 |

## 陷阱

- **私人資料**：`facts.json` 的 `portfolio_positions` 大於 0 時是私人模式，範圍是本次所有導覽，不只本檔（[SKILL 私人資料](../SKILL.md#私人資料)）：`page_checks.py` 的輸出整個寫到 `$OUT/.private/`，推送的 summary 只列每條檢查的狀態，人工檢查的證據只寫行號與行數，不抄庫存行。
- A5 只比 LLM 產出的標記 `AI 推論` 與 `（推論）`；說明文字裡的一般用語「推論」不算。
- `/actions/:exchange/:symbol` 轉址到個股頁，`action-detail` 截圖的是轉址後的個股研究條件分頁；分頁按鈕 id 同個股（`#stock-tab-research`）。
- 桌面表格每列在 innerText 裡可能分成幾行（收盤格有兩行），A4 只認列的最後一行（資料日格＋連結格）。390 的手機卡片在 1280 不顯示，不會重複計數。

## 判定

- 通過：A1～A10 全部通過。
- 失敗：任一條失敗，列出編號、預期與實際。
- 無法判定：沒有失敗，但有檢查無法判定（截圖未 ready、分頁按鈕找不到、API 非 200、沒有選到個股，或上游沒通過，見 [README 三態與上游](README.md#三態與上游)）；列出 URL 或上游編號。

## 輸出格式

```markdown
### 行動 `/actions`：通過

| 檢查 | 結果 | 原因類別 | 證據 |
| --- | --- | --- | --- |
| A3 | 通過 | — | 今日候選 `顯示 20／20 檔`；其他成立條件 `顯示 0／51 檔` |
| A4 | 通過 | — | 20 列各有資料日 ≤ 2026/10/22；data_as_of = facts |
| A6 | 通過 | — | TWSE 3004 研究動作 `暫無研究條件`，`資料日：2026/10/21` = data_cutoff |

截圖：shots/actions-1280.png、shots/actions-390.png、shots/action-detail-1280.png
```
