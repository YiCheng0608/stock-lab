# 行動 `/actions`

入口：主導航「行動」，`ActionsPage`（行動中心）；`/actions/:exchange/:symbol` 共用 `StockPage`（`frontend/src/App.tsx`）。路徑：個股檔的 `E`、`S` → 行動詳情（追蹤）。

## API

| 檔名 | URL（前綴 `http://127.0.0.1:8227/api`） |
| --- | --- |
| `actions.json` | `/actions?limit=20` |
| `portfolio.json` | `/portfolio?page=1&page_size=20` |
| `action-detail.json` | `/actions/<E>/<S>` |

## 截圖

| 名稱 | 參數 |
| --- | --- |
| `actions` | `--url http://127.0.0.1:4227/actions --name actions`（1280 與 390） |
| `action-detail` | `--url http://127.0.0.1:4227/actions/<E>/<S> --name action-detail --widths 1280 --click '#stock-tab-research'` |

## 預期資料與標記

| 區塊 | 資料來源 | 必須顯示的來源與資料日期 | 「推論」位置 | 空資料文案 |
| --- | --- | --- | --- | --- |
| 我的庫存 | `portfolio.json` | 每筆 `記錄來源 … · 記錄日期 …`（本地記錄，標「來源／日期待核實」） | — | `尚未建立庫存。` |
| 行動卡（優先處理、待補、其他） | `actions.json` | 每張卡 `資料日 YYYY/MM/DD` | 本頁沒有 LLM 產出，不應出現 `推論` | `目前沒有庫存風險或可執行條件。` |
| 分頁 | `actions.json` 的 `meta` | `第 1 頁 · 本頁 <items 數> 筆 · 共 <meta.total 千分位> 筆` | — | `沒有符合條件的資料。` |
| 行動詳情（研究條件分頁） | `action-detail.json` 的 `decision_summary` | `資料日期：…`、`資料日：… · 價位語意：…` | 同個股 S5 | `尚無行動摘要。` |

## 檢查

| 編號 | 類型 | 檢查 | 怎麼判 |
| --- | --- | --- | --- |
| A1 | CI | 頁面可用 | 每張截圖 `ready` true、`missingClicks` 空、`httpErrors` 與 `consoleErrors` 空、`overflow` false |
| A2 | CI | 庫存區 | `actions-1280.txt` 有整行 `我的庫存`；`portfolio.json` 的 `items` 空時有整行 `尚未建立庫存。`，否則 `記錄來源 ` 開頭的行數 = `items` 數 |
| A3 | CI | 分頁與總數 | `第 1 頁 · 本頁 <items 數> 筆 · 共 <meta.total 千分位> 筆` 為整行 |
| A4 | CI | 卡片資料日 | `查看個股詳情 →` 的行數 k（展開的待補區也算）= `^資料日 [0-9]{4}/[0-9]{2}/[0-9]{2}$` 的行數；這些日期都等於 `meta.data_as_of` 的 `YYYY/MM/DD` 或更早，且 `meta.data_as_of` 等於 `facts.json` 的 `market_latest_trading_date` |
| A5 | CI | 沒有未標示的推論 | `actions-1280.txt` 不含 `AI 推論` 與 `（推論）` 兩個字串（`grep -F`；本頁不放 LLM 產出；出現就判失敗並記行號） |
| A6 | CI | 追蹤詳情 | `action-detail-1280.txt` 有整行 `<S>` 與 `研究動作`；`decision_summary` 非 null 時有 `資料日：` 開頭的行，其日期等於 `decision_summary.data_cutoff` 的 `YYYY/MM/DD`（前 10 字）；null 時有 `尚無行動摘要。` |
| A7 | CI | 路徑一致 | `action-detail` 頁首代號與名稱等於個股頁（`stock.json` 的 `instrument.symbol`、`name`） |

## 陷阱

- **私人資料**：`facts.json` 的 `portfolio_positions` 大於 0 時是私人模式，範圍是本次所有導覽，不只本檔（[SKILL Doctor 第 4 步](../SKILL.md#2-doctor)）：截圖與 API JSON 寫到 `$OUT/.private/`，`results/*.md` 只寫行號與行數，不抄庫存行。
- A5 只比 LLM 產出的標記 `AI 推論` 與 `（推論）`；說明文字裡的一般用語「推論」不算。
- `/actions/:exchange/:symbol` 共用 `StockPage`，分頁按鈕 id 同個股（`#stock-tab-research`）。

## 判定

- 通過：A1～A7 全部通過。
- 失敗：任一條失敗，列出編號、預期與實際。
- 無法判定：截圖未 ready、分頁按鈕找不到或 API 非 200；依賴它的檢查不判。

## 輸出格式

```markdown
### 行動 `/actions`：通過

| 檢查 | 結果 | 原因類別 | 證據 |
| --- | --- | --- | --- |
| A3 | 通過 | — | `第 1 頁 · 本頁 20 筆 · 共 1,858 筆` |
| A4 | 通過 | — | 20 張卡、20 行 `資料日 2026/10/21`；data_as_of 2026-10-21 = facts |
| A6 | 通過 | — | TWSE 3004 研究動作 `暫無研究條件`，`資料日：2026/10/21` = data_cutoff |

截圖：shots/actions-1280.png、shots/actions-390.png、shots/action-detail-1280.png
```
