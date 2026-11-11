# 個股 `/stocks`

入口：主導航「個股」，`StocksPage`（目錄）與 `StockPage`（`/stocks/:exchange/:symbol`，`frontend/src/App.tsx`、`frontend/src/stock/`；六個分頁 `chart`、`chips`、`financials`、`news`、`research`、`data`，按鈕 id 為 `stock-tab-<分頁>`）。路徑：族群詳情第一個成員 → 個股頁（族群榜空時改用明日候選 #1、再改用市場列表第一筆，見 [README 選股](README.md#選股)）。

導覽列搜尋的即時建議（`frontend/src/components/NavSearch.tsx`，#599）不在本頁檢查：建議清單只在輸入時出現，截圖頁面文字不含它，`page_checks.py` 不需更新；建議的請求、鍵盤與滑鼠操作、Esc、Enter 導到 `/stocks?q=` 由前端測試（`search.test.ts`、`components/ui/ui.test.tsx`）涵蓋，`securities_only` 與排序由 `backend/tests/test_api.py` 涵蓋。

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
| 前端檔 | `frontend/src/stock/StockSummaryCard.tsx` |
| 前端檔 | `frontend/src/stock/stockSummary.ts` |
| 前端檔 | `frontend/src/stock/StockCutoffControl.tsx` |
| 前端檔 | `frontend/src/tracking/TrackingViews.tsx` |
| 前端檔 | `frontend/src/stock/StrategyBoardPanel.tsx` |
| 前端檔 | `frontend/src/stock/strategyBoard.ts` |
| 前端檔 | `frontend/src/stock/stockTabs.ts` |
| 前端檔 | `frontend/src/stock/StockFundamentalsPanel.tsx` |
| 前端檔 | `frontend/src/stock/stockFundamentals.ts` |
| API route | `GET /dashboard` |
| API route | `GET /data-date` |
| API route | `GET /stocks` |
| API route | `GET /stocks/{exchange}/{symbol}` |
| API route | `GET /stocks/{exchange}/{symbol}/bars` |
| API route | `GET /news` |

## 截圖

| 名稱 | 參數 |
| --- | --- |
| `stocks` | `--url <WEB>/stocks --name stocks`（1280 與 390） |
| `stock` | `--url <WEB>/stocks/<E>/<S> --name stock`（1280 與 390，預設「走勢」分頁） |
| `stock-chips` | 同上 URL，`--name stock-chips --widths 1280 --click '#stock-tab-chips'` |
| `stock-financials` | 同上 URL，`--name stock-financials --widths 1280 --click '#stock-tab-financials'` |
| `stock-research` | 同上 URL，`--name stock-research --widths 1280 --click '#stock-tab-research'` |
| `stock-news` | 同上 URL，`--name stock-news --widths 1280 --click '#stock-tab-news'` |
| `stock-data` | 同上 URL，`--name stock-data --widths 1280 --click '#stock-tab-data'` |

## 預期資料與標記

| 區塊 | 資料來源 | 必須顯示的來源與資料日期 | 「推論」位置 | 空資料文案 |
| --- | --- | --- | --- | --- |
| 目錄表 | `stocks.json` | 表頭說明單位；`第 1／<total_pages> 頁 · 共 <total> 筆` | — | `沒有符合條件的標的。` |
| 頁首 | `stock-bars.json`（日線） | `資料 <I/>` badge 與 `來源 <交易所名稱>`；`stock.json` 的 `trading_halt` 有值時（減資停止買賣中，#582），`來源` 之後一行 `停止買賣中（<reason_label>，預計 <resume_date> 恢復）` | — | `資料日期未提供`、`尚無已核對的價格來源` |
| 摘要卡（#519） | `stock.json` 的 `strategy_board`、`decision_summary` | 第一欄 `目前判斷` 旁的 `資料 <strategy_board.as_of/>` badge | 不放 AI 內容 | `此股尚無策略判定資料。`、`尚無行動摘要。` |
| K 線與技術指標 | `stock-bars.json`（`limit=250`；按「全部」或區間起日早於第一根時，圖表另取 `limit=1500`，#600） | 卡片標題下 `資料 <I/>`、`來源 …`、`日線批次計算於 …`；工具列日K／週K 之後的區間按鈕 `1M` `3M` `6M` `1Y` `全部`（預設 `6M`） | — | 無日線時的 EmptyState |
| 籌碼 | `stock.json` 的 `chips`（API 只回最近 30 筆、日期由舊到新，#601；表格由新到舊） | 卡片 `法人與融資`；每筆來源說明分兩行 `法人：…（<source>） · 資料截至：… · 收集：…` 與 `融資：…`，該筆沒有那份官方檔時是 `法人：無資料`／`融資：無資料`（#395）；`券商／分點` 區塊 | — | `尚無可核實的籌碼資料。` |
| 研究條件 | `stock.json` 的 `strategy_board`、`decision_summary`、`candidate` | 策略總表 `資料 <strategy_board.as_of/>`；`資料日期：<I/>`（時間摘要）、`資料日：<I/> · 價位語意：…` | 策略總表有候選列（`strategy_board.candidate` 非 null）時，候選列的 `AI 推論` 與來源行 `（推論）`（同今日 T8）；觀察價位在 `條件未成立・觀察價位` 標籤之下，不是推論 | `此股尚無策略判定資料。`、`尚無行動摘要。` |
| 財務（#528） | `stock.json` 的 `fundamentals`（API 已依截止日篩掉可得日較晚的列，期別由新到舊） | 卡片 `季報營收與 EPS` 之後的 `資料 <最新一列 data_as_of/>` badge；每列的可得日與來源，表格下 `來源：…` | — | ETF `ETF 沒有公司財報，不適用。`；新上市與其他股票各一句（UI_COPY_SPEC §8.2 財務分頁） |
| 月營收（#530） | `stock.json` 的 `monthly_revenues`（API 已依截止日篩掉可得日較晚的月份，由新到舊，最多 12 個月） | 季報卡之下的卡片 `月營收` 之後的 `資料 <最新月份 data_as_of/>` badge；每列的可得日與來源，表格下 `來源：…`；`corrected: true` 的月份（#543）在可得日之後的「更正」欄寫 `已更正`（只有這種月份存在時才有這一欄），`來源：…` 之後每個更正月一行 `<YYYY 年 N 月>已更正：原快照營收 …` | — | ETF `ETF 不申報月營收，不適用。`；新上市與其他股票各一句（UI_COPY_SPEC §8.2 財務分頁） |
| 新聞與公告 | `stock-news.json`（只留交易所＋代號相符） | 每張卡時間行與來源 | 有 AI 判讀的卡接 `AI 推論` | `尚無與此股已核實關聯的新聞或公告。` |
| 資料來源 | `stock.json`、`stock-bars.json` | `行情來源`、`K 線資料日期` 兩列與當日行情來源品質行 `<品質說明> · 資料日 <I/>`（例如 `行情來源完整 · 資料日 2026/10/21`） | — | `待核實` |

## 檢查

| 編號 | 類型 | 檢查 | 怎麼判 |
| --- | --- | --- | --- |
| S1 | CI | 頁面可用 | 不依賴選股：沒有 `E`、`S` 時只驗 `stocks` 兩張截圖。每張截圖 `ready` true、`missingClicks` 空、`httpErrors` 與 `consoleErrors` 空、`overflow` false |
| S2 | CI | 目錄（不依賴選股） | `stocks-1280.txt` 有表頭整行 `代號\t名稱\t交易所\t類型\t最近收盤（元）\t目前研究動作`（「策略判斷資料」併入研究動作欄，#602）；`items` 依類型（股票、ETF、新上市）再依代號排列（#602 預設排序）；`items[0].instrument.symbol` 開頭的列存在；`第 1／<total_pages> 頁 · 共 <total 千分位> 筆` 為整行 |
| S3 | CI | 頁首資料日與來源 | `stock-1280.txt` 有整行 `<S>`；第一個 `資料 ` 開頭的行在導覽列（`資料 <facts D/>`），第二個是 `資料 <I/>`，其下一行以 `來源 ` 開頭且不是 `來源 尚無已核對的價格來源`；`I` 等於 `stock-bars.json` 的 `data_as_of` |
| S4 | CI | K 線卡 | 整行 `K 線與技術指標` 的下一行是 `資料 <I/>`；有 `來源 ` 開頭的行與 `日線批次計算於` 開頭的行 |
| S5 | CI | 研究條件 | `stock-research-1280.txt` 有整行 `研究動作`；有 `資料日期：<I/>` 開頭的行與 `資料日：<I/> · 價位語意：` 開頭的行（`decision_summary` 為 null 時改查 `尚無行動摘要。`）；`strategy_board.candidate` 非 null 時再查整行 `每日候選`、`AI 推論` 至少 1 行、`^來源：` 行結尾為 `（推論）`（#274 起候選資訊在策略總表的候選列，不再有 `明日候選` 區） |
| S6 | CI | 新聞與公告 | `stock-news-1280.txt` 有整行 `<S> 相關新聞`；`stock-news.json` 中 `instruments[]` 有 `exchange` = `<E>` 且 `symbol` = `<S>` 的則數為 0 時有 `尚無與此股已核實關聯的新聞或公告。`，否則時間行數（同新聞 N3 的規則）≥ 1 |
| S7 | CI | 資料來源 | `stock-data-1280.txt` 整行 `K 線資料日期` 的下一行是 `<I/>`；整行 `行情來源` 的下一行非空且不是 `待核實`；有 `資料日 <I/>` 結尾的行 |
| S8 | CI | 資料日與 DB 一致 | `I` 的上游，先於 S3～S7 跑；`I` 缺少（該股沒有日線）判無法判定。`I` 等於 `facts-stock.json` 的 `instrument.latest_trading_date`；`instrument.source` 非空 |
| S9 | CI | 籌碼 | `stock-chips-1280.txt` 有整行 `法人與融資` 與 `券商／分點`；`stock.json` 的 `chips` 空時有整行 `尚無可核實的籌碼資料。`，否則有以 `<chips[-1].date 的 YYYY/MM/DD>\t` 開頭的行（表格第一列是最新一筆），且 `法人：`、`融資：` 開頭的行數各 = `min(30, chips 數)`；第一個 `法人：` 行（最新一筆）在 `chips[-1].institutional` 為 null 時是整行 `法人：無資料`，否則含 `（<institutional.source>） · 資料截至：<institutional.data_as_of 的 YYYY/MM/DD> · 收集：`，`融資：` 行同理對 `margin`（#395） |
| S10 | CI | 策略總表（#274） | `stock-research-1280.txt` 有整行 `策略總表`，下一行是 `資料 <strategy_board.as_of 的 YYYY/MM/DD>`（`as_of` 為 null 時改查 `此股尚無策略判定資料。`）；`strategies` 每一列在桌面表格有 `<label><TAB>` 開頭的行，下一行是 `<狀態>` 或以 `<狀態><TAB>` 開頭（成立列的最早執行日在 badge 下方另起一行；`conditional` 成立、`observation` 觀察、`data_incomplete` 資料不足、`not_applicable` 不適用）；從 `策略總表` 那一行起（#519：之前的摘要卡會重複最接近成立那一條的觀察價位），整行 `條件未成立・觀察價位` 的行數等於 `levels.kind=observation` 的列數，而且不出現在成立列的範圍內（成立價位與觀察價位不混）；`candidate` 非 null 時有 `第 <rank> 名 · 總分 <round(total_score×100)> · ` 開頭的行，null 時沒有整行 `每日候選` |
| S11 | CI | 摘要卡（#519） | `stock-1280.txt` 有整行 `目前判斷`，它之後、分頁籤 `走勢` 之前是摘要卡：`目前判斷` 後三行內有判斷 badge，依 [UI_COPY_SPEC §8.2 摘要卡](../../../../docs/UI_COPY_SPEC.md#82-個股詳情的第一屏) 的順序由 `stock.json` 推得（沒有行動摘要也沒有策略總表 `無資料`；`reduce_exit` 持倉風險；`strategy_board.candidate` 非 null 條件成立（#581 前寫「可買」）；`hold_observe` 持倉觀察；`manual_review` 需人工判讀；每列 `not_applicable` 不適用；行動摘要資料不足 資料不足；有 `conditional` 列 條件成立；其他 觀察）；候選的下一行是 `每日候選第 <rank> 名 · 總分 <round(total_score×100)> · <策略>`，資料不足且有 `gap_reasons` 時下一行是各 `label` 以 `；` 連接，觀察且有 `primary_reason` 時下一行是它的 `label`，無資料的下一行是 `尚無行動摘要。`；之後有整行 `最接近成立`、`規則價位`（`strategies` 空時不查 `規則價位`）與 `完整條件 →` |
| S12 | CI | 財務（#528） | `stock-financials-1280.txt` 有整行 `季報營收與 EPS`。`stock.json` 的 `fundamentals` 空時：依 `instrument.instrument_type` 有整行原因句（`etf` 為 `ETF 沒有公司財報，不適用。`，`ipo` 與其他各一句，見 [UI_COPY_SPEC §8.2 財務分頁](../../../../docs/UI_COPY_SPEC.md#82-個股詳情的第一屏)），且沒有期別列。不空時：標題之後有 `資料 <最新一列 data_as_of 的 YYYY/MM/DD>`；每一列有以 `<期別>\t<營收÷100,000，兩位小數>\t<EPS 兩位小數>\t<ROE 兩位小數>\t<可得日>\t` 開頭的行（沒有值的格是 `來源未提供`，期別 `Q<n>` 寫 `YYYY 年第 n 季`），順序與 API 相同；表格下有 `來源：` 開頭的行 |
| S13 | CI | 月營收（#530） | `stock-financials-1280.txt` 有整行 `月營收`，以下都從這一行起找。`stock.json` 的 `monthly_revenues` 空時：依 `instrument.instrument_type` 有整行原因句（`etf` 為 `ETF 不申報月營收，不適用。`，`ipo` 與其他各一句），且沒有月份列。不空時：有 `資料 <最新月份 data_as_of 的 YYYY/MM/DD>`；每個月有以 `<YYYY 年 M 月>\t<營收÷100,000，兩位小數>\t<年增率一位小數，正數帶 +>\t<可得日>\t` 開頭的行（沒有值的格是 `來源未提供`），順序與 API 相同（已更正月份的 `已更正` 在可得日之後那格，不在比對的開頭內，#543）；表格下有 `來源：` 開頭的行 |

## 陷阱

- 頁面文字裡第一個 `資料 ` 開頭的行是導覽列的 `資料 <D/>`，頁首的 `資料 <I/>` 是第二個（S3）。
- 停止買賣中的股票（`trading_halt` 有值，#582）頁首多一行 `停止買賣中（…）`，在 `來源 ` 那行之後，所以 S3 的「下一行以 `來源 ` 開頭」照舊成立。假資料沒有停止買賣（`trading_halts` 在 `OMITTED_TABLES`），這行由後端 `test_trading_halts` 與前端 `stockBars.test.tsx` 驗；真資料模式在停止買賣期間抽到這種股票時，人工核對日期與 `trading_halt.resume_date` 一致。
- 預設分頁是「走勢」，其他四個分頁靠 `--click '#stock-tab-<分頁>'` 切換；按鈕找不到會列在 `missingClicks`。
- K 線卡工具列的區間按鈕（#600）各自成行出現在頁面文字裡（`週K` 與 `MA5` 之間）；截圖只拍載入後的預設 `6M`，按鈕切換、手動縮放取消選取與十字游標由前端測試與 PR 的瀏覽器實測涵蓋，目前沒有檢查讀這幾行。`最近 <count> 根日線` 是圖表正在畫的序列：預設 250 根，按「全部」後是另取的全部日線。
- `screenshot.cjs` 會展開所有 `<details>`，籌碼的「資料來源與原始值」、資料來源的「查看原始行情表」內容都在頁面文字裡（S9 的 `法人：`／`融資：` 行數靠這點）。
- 「有 AI 判讀」的定義見 [news.md 陷阱](news.md#陷阱)。
- 個股清單在 640px 以下改成每檔一張卡（表格 `display:none`，超過 10 張的其餘收在「顯示其餘 N 檔」`<details>`，#300），`stocks-390.txt` 沒有以 tab 分欄的表格列；目前沒有檢查讀它的文字，只有 S1 看版面。
- 個股頁頁首的研究截止日期在所有寬度都收成「研究截止日期：…」開關（手機 #300、桌面 #635），沒套用截止日時頁面文字只有這一行。
- 策略總表在 640px 以下改成每策略一張卡（表格 `display:none`），所以 S10 只讀 1280 的文字；`screenshot.cjs` 展開的 `<details>`（條件明細、評分細節）也在文字裡，S10 只比對表格列、狀態行與觀察價位標籤。

## 判定

- 通過：S1～S13 全部通過。
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
