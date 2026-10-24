# 個股 `/stocks`

入口：主導航「個股」，`StocksPage`（目錄）與 `StockPage`（`/stocks/:exchange/:symbol`，`frontend/src/App.tsx`、`frontend/src/stock/`；五個分頁 `chart`、`chips`、`news`、`research`、`data`，按鈕 id 為 `stock-tab-<分頁>`）。路徑：族群詳情第一個成員 → 個股頁（族群榜空時改用明日候選 #1、再改用市場列表第一筆，見 [README 選股](README.md#選股)）。

## API

| 檔名 | URL（前綴 `<API>/api`，`<API>` 為 API 的 origin） |
| --- | --- |
| `stocks.json` | `/stocks?page=1&page_size=30` |
| `stock.json` | `/stocks/<E>/<S>` |
| `stock-bars.json` | `/stocks/<E>/<S>/bars?interval=day&limit=250` |
| `stock-news.json` | `/news?symbol=<S>&limit=50` |

`E`、`S` 依 [README 選股](README.md#選股)，來源寫在 `summary.md` 開頭。另跑 `"$PY" -B "$WT/.claude/skills/verify-stock-lab/db_facts.py" "$V/stock.db" <E> <S> > "$OUT/facts-stock.json"`，`I` = 其中 `instrument.latest_trading_date`。

## 驗證範圍

改到下列前端檔或 API route 時，CI 驗這一頁；規則見 [README 驗證範圍](README.md#驗證範圍)。

| 種類 | 對象 |
| --- | --- |
| 前端檔 | `frontend/src/candidates/CandidateViews.tsx` |
| 前端檔 | `frontend/src/news/NewsViews.tsx` |
| 前端檔 | `frontend/src/stock/StockBarsChart.tsx` |
| 前端檔 | `frontend/src/stock/StockHeader.tsx` |
| API route | `GET /dashboard` |
| API route | `GET /stocks` |
| API route | `GET /stocks/{exchange}/{symbol}` |
| API route | `GET /stocks/{exchange}/{symbol}/bars` |
| API route | `GET /news` |

## 截圖

| 名稱 | 參數 |
| --- | --- |
| `stocks` | `--url <WEB>/stocks --name stocks`（1280 與 390） |
| `stock` | `--url <WEB>/stocks/<E>/<S> --name stock`（1280 與 390，預設「圖表與指標」分頁） |
| `stock-chips` | 同上 URL，`--name stock-chips --widths 1280 --click '#stock-tab-chips'` |
| `stock-research` | 同上 URL，`--name stock-research --widths 1280 --click '#stock-tab-research'` |
| `stock-news` | 同上 URL，`--name stock-news --widths 1280 --click '#stock-tab-news'` |
| `stock-data` | 同上 URL，`--name stock-data --widths 1280 --click '#stock-tab-data'` |

## 預期資料與標記

| 區塊 | 資料來源 | 必須顯示的來源與資料日期 | 「推論」位置 | 空資料文案 |
| --- | --- | --- | --- | --- |
| 目錄表 | `stocks.json` | 表頭說明單位；`第 1／<total_pages> 頁 · 共 <total> 筆` | — | `沒有符合條件的標的。` |
| 頁首 | `stock-bars.json`（日線） | `資料 <I>` badge 與 `來源 <交易所名稱>` | — | `資料日期待核實`、`尚無已核對的價格來源` |
| K 線與技術指標 | `stock-bars.json` | 卡片標題下 `資料 <I>`、`來源 …`、`日線批次計算於 …` | — | 無日線時的 EmptyState |
| 法人籌碼 | `stock.json` 的 `chips`（日期由舊到新，表格只列最近 30 筆、由新到舊） | 卡片 `法人與融資`；每筆來源說明 `來源：… · 資料截至：…`；`券商／分點` 區塊 | — | `尚無可核實的籌碼資料。` |
| 研究條件 | `stock.json` 的 `decision_summary`、`candidate` | `資料日期：<I/>`（時間摘要）、`資料日：<I/> · 價位語意：…` | 本股在最新候選內時，`明日候選` 區的 `推論`、`AI 推論` 與來源行 `（推論）`（同今日 T8） | `尚無行動摘要。` |
| 新聞與公告 | `stock-news.json`（只留交易所＋代號相符） | 每張卡時間行與來源 | 有 AI 判讀的卡接 `AI 推論` | `尚無與此股已核實關聯的新聞或公告。` |
| 資料說明 | `stock.json`、`stock-bars.json` | `行情來源`、`K 線資料日期` 兩列與當日行情來源品質行 `<品質說明> · 資料日 <I/>`（例如 `行情來源完整 · 資料日 2026/10/21`） | — | `待核實` |

## 檢查

| 編號 | 類型 | 檢查 | 怎麼判 |
| --- | --- | --- | --- |
| S1 | CI | 頁面可用 | 不依賴選股：沒有 `E`、`S` 時只驗 `stocks` 兩張截圖。每張截圖 `ready` true、`missingClicks` 空、`httpErrors` 與 `consoleErrors` 空、`overflow` false |
| S2 | CI | 目錄（不依賴選股） | `stocks-1280.txt` 有表頭整行 `代號\t名稱\t交易所\t類型\t最近收盤\t目前研究動作\t策略判斷資料`；`items[0].instrument.symbol` 開頭的列存在；`第 1／<total_pages> 頁 · 共 <total 千分位> 筆` 為整行 |
| S3 | CI | 頁首資料日與來源 | `stock-1280.txt` 有整行 `<S>`；第一個 `資料 ` 開頭的行在導覽列（`資料 <facts D>`），第二個是 `資料 <I>`，其下一行以 `來源 ` 開頭且不是 `來源 尚無已核對的價格來源`；`I` 等於 `stock-bars.json` 的 `data_as_of` |
| S4 | CI | K 線卡 | 整行 `K 線與技術指標` 的下一行是 `資料 <I>`；有 `來源 ` 開頭的行與 `日線批次計算於` 開頭的行 |
| S5 | CI | 研究條件 | `stock-research-1280.txt` 有整行 `研究動作`；有 `資料日期：<I/>` 開頭的行與 `資料日：<I/> · 價位語意：` 開頭的行（`decision_summary` 為 null 時改查 `尚無行動摘要。`）；`stock.json` 的 `candidate` 非 null 時再查整行 `明日候選`、`AI 推論` 至少 1 行、`^來源：` 行結尾為 `（推論）` |
| S6 | CI | 新聞與公告 | `stock-news-1280.txt` 有整行 `<S> 相關新聞`；`stock-news.json` 中 `instruments[]` 有 `exchange` = `<E>` 且 `symbol` = `<S>` 的則數為 0 時有 `尚無與此股已核實關聯的新聞或公告。`，否則時間行數（同新聞 N3 的規則）≥ 1 |
| S7 | CI | 資料說明 | `stock-data-1280.txt` 整行 `K 線資料日期` 的下一行是 `<I>`；整行 `行情來源` 的下一行非空且不是 `待核實`；有 `資料日 <I/>` 結尾的行 |
| S8 | CI | 資料日與 DB 一致 | `I` 的上游，先於 S3～S7 跑；`I` 缺少（該股沒有日線）判無法判定。`I` 等於 `facts-stock.json` 的 `instrument.latest_trading_date`；`instrument.source` 非空 |
| S9 | CI | 法人籌碼 | `stock-chips-1280.txt` 有整行 `法人與融資` 與 `券商／分點`；`stock.json` 的 `chips` 空時有整行 `尚無可核實的籌碼資料。`，否則有以 `<chips[-1].date 的 YYYY/MM/DD>\t` 開頭的行（表格第一列是最新一筆），且含 ` · 資料截至：` 的行數 = `min(30, chips 數)` |

## 陷阱

- 頁面文字裡第一個 `資料 ` 開頭的行是導覽列的 `資料 <D>`，頁首的 `資料 <I>` 是第二個（S3）。
- 預設分頁是「圖表與指標」，其他四個分頁靠 `--click '#stock-tab-<分頁>'` 切換；按鈕找不到會列在 `missingClicks`。
- `screenshot.cjs` 會展開所有 `<details>`，籌碼的「資料來源與原始值」、資料說明的「查看原始行情表」內容都在頁面文字裡（S9 的來源行數靠這點）。
- 「有 AI 判讀」的定義見 [news.md 陷阱](news.md#陷阱)。

## 判定

- 通過：S1～S9 全部通過。
- 失敗：任一條失敗，列出編號、預期與實際。
- 無法判定：沒有失敗，但有檢查無法判定（截圖未 ready、分頁按鈕找不到（`missingClicks`）、API 非 200、沒有選到個股，或上游沒通過，見 [README 三態與上游](README.md#三態與上游)）；列出 URL 或上游編號。

## 輸出格式

```markdown
### 個股 `/stocks`：通過（TWSE 3004 豐達科）

| 檢查 | 結果 | 原因類別 | 證據 |
| --- | --- | --- | --- |
| S3 | 通過 | — | 頁首 `資料 2026-10-21`、`來源 臺灣證券交易所`；bars data_as_of 2026-10-21 |
| S6 | 通過 | — | 0 則相符新聞，顯示 `尚無與此股已核實關聯的新聞或公告。` |

截圖：shots/stock-1280.png、shots/stock-390.png、shots/stock-research-1280.png
```
