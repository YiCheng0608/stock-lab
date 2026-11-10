## verify-stock-lab 真資料結果（2026-11-10 13:04 台北，正式 run）

- 程式：`task/606-real-verify` @ `86b62666`（= `origin/master`，工作樹乾淨、沒有 commit；不加 `--g7`）
- 副本：資料日 2026-11-09（`facts.json` 的 `market_latest_trading_date`；`copy.json` 的 `source_latest_trading_date` 2026-11-09），alembic `0030_trading_halts`（= `migration_revisions.py` 最後一項，沒有跑 `init-db`），3,450,974,208 bytes，複製 490.5 秒，`quick_check` ok；`portfolio_positions` 0，不是私人模式
- 個股 E／S：TWSE 1216，今日榜 #1 族群「食品」的第一個成員
- 證據：https://github.com/YiCheng0608/stock-lab/tree/pr-assets/606/20261110-1304
- 人工檢查（獨立 session 判讀，[`manual/judgement.md`](manual/judgement.md)）：T10 通過（3/3）；N7 通過（5/5）；N8 通過（5/5）
- `page_checks.py` 預設 `--jobs 4`：60 項，通過 26、失敗 3、無法判定 31，耗時 833 秒（截圖 745 秒）。失敗與無法判定都來自截圖時 API 回 500／504：`api-pool-errors.log` 有 35 次 `QueuePool limit of size 5 overflow 10 reached, connection timed out, timeout 30.00`，容器沒有 OOM、沒有重啟；逐一呼叫時都是 200（`/api/dashboard` 4.06 秒）。同時間 `task-598-run` 持續占用約 100% CPU。同一份副本、同一組服務用 `--jobs 1` 補跑（`20261110-1330-jobs1`），60 項全部通過
- 390px 量測（`390px/`）：候選列「總分」被「AI 推論 ▸」按鈕蓋住，標籤右緣超出卡片 3.8～5 px（產品缺陷，見 Issue 回報）；個股摘要卡的 RR 依據沒有溢出

| 導覽 | 結果 | 失敗或無法判定的檢查（原因類別） |
| --- | --- | --- |
| 今日可買 `/` | 通過 | — |
| 新聞 `/news` | 通過 | — |
| 族群 `/themes` | 失敗 | G1：theme-detail 未 ready，`/api/dashboard`、`/api/news?theme_id=…` 504／500（工具缺口・環境：並行截圖加上主機 CPU 被占用，連線池耗盡）；G5～G8 無法判定（上游同 G1，工具缺口）。補充 run 全部通過 |
| 個股 `/stocks` | 失敗 | S1：stocks、stock 各分頁未 ready，`/api/dashboard`、`/api/stocks…` 504／500，tab missingClicks（工具缺口・環境，同上）；S2～S7、S10～S13 無法判定（上游同 S1，工具缺口）。補充 run 全部通過 |
| 觀察中 `/watch` | 失敗 | A1：actions 未 ready，`/api/tracking…`、`/api/actions…`、`/api/portfolio…`、`/api/dashboard` 500／504（工具缺口・環境，同上）；A2～A18 無法判定（上游同 A1，工具缺口）。補充 run 全部通過 |

## verify 檢查結果（2026-11-10 13:15 台北）

- 程式：`task/606-real-verify` @ `86b62666`（工作樹乾淨）
- API `http://api:8000`、前端 `http://web:8080`、DB `stock.db`
- 個股 E／S：TWSE 1216，今日榜 #1 族群「食品」的第一個成員
- 60 項：通過 26、失敗 3、無法判定 31、已知失敗 0；耗時 833 秒

### 人工檢查樣本（依 features 規則抽樣，判讀見 SKILL 真資料模式第 3 步）

| 檢查 | 樣本 |
| --- | --- |
| T10 | 3 筆，`manual/T10.json` |
| N7 | 5 筆，`manual/N7.json` |
| N8 | 5 筆，`manual/N8.json` |

### 今日可買 `/`：通過

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| T1 | 通過 | 6 張截圖 ready，無錯誤，無橫向捲動 |
| T2 | 通過 | `資料 2026/11/09` = facts 2026-11-09 |
| T3 | 通過 | `資料截至 2026/11/09 · TWSE／TPEx 官方資料 · 官方單日快照` |
| T4 | 通過 | `資料 2026/11/09`；B = facts 2026-11-09 |
| T5 | 通過 | 5 列（`#n` 與名稱）= items 前 5 名；`1／5／20 日為相對加權指數的報酬` |
| T6 | 通過 | 前 5 則標題都在；有 AI 判讀的卡片方向與 AI 相同並標 `AI 推論`：26676 `可能正向`、26654 `可能正向`、26689 `可能正向`、26690 `可能正向`、26677 `可能正向` |
| T7 | 通過 | `資料 2026/11/09`、`11 檔`；名次列 11、來源行 11 = items；C = facts |
| T8 | 通過 | 11 檔新聞情緒推論的來源行以 `（推論）` 結尾；`AI 推論` 16 行；免責句 11 行；入口 `AI 推論 ▸` 11、`AI 說明 ▸` 0 |
| T9 | 通過 | 首頁沒有 `關注標的`、`明日候選`；沒有持倉風險提示列 |
| T11 | 通過 | 2026-11-09：TWSE 41,661.70、TPEx 321.97；範圍 `上市為集中市場總計（含 ETF、權證等）；上櫃為上櫃股票` |
| T12 | 通過 | `今日可買`（today-1280.txt 第 23 行）→ `熱門族群`（today-1280.txt 第 905 行）、`重點新聞`（today-1280.txt 第 941 行） |
| T13 | 通過 | 11 張卡：`加入追蹤` 11、`已在追蹤` 0 = open_plan_id 非 null |
| T14 | 通過 | `加權 41,661.70 +4.94%`、`櫃買 321.97 +5.90%`、`資料 2026/11/09`、`看大盤 →`（today-1280.txt 第 19 行） |
| T15 | 通過 | `加權指數日線` `資料 2026/11/09`、`最近 250 根日線；缺日不補、停牌不畫 K 線`、最新 `2026/11/09\t40,347.28\t42,349.36\t40,347.28\t41,661.70`；`櫃買指數日線` `資料 2026/11/09`、`最近 250 根日線；缺日不補、停牌不畫 K 線`、最新 `2026/11/09\t305.51\t323.84\t305.51\t321.97`；`台指期近月日線` `資料 2026/11/06`、`最近 250 根日線；缺日不補、停牌不畫 K 線`、最新 `2026/11/06\t38,888\t40,690\t37,694\t39,786` |
| T16 | 通過 | 美股；`加權指數\t41,661.70\t+1,960.06\t+4.94%\t2026/11/09\t之下 季線 46,360.77\t臺灣證券交易所`；`櫃買指數\t321.97\t+17.95\t+5.90%\t2026/11/09\t之下 季線 396.13\t證券櫃檯買賣中心`；`台指期近月 合約 2026/11\t39,786\t-2,129\t-5.08%\t2026/11/06 非最新\t之下 季線 46,511\t臺灣期貨交易所`；`S&P 500\t7,549.94\t+173.08\t+2.35%\t2026/11/09\t之下 季線 7,678.66\tFinMind`；`NASDAQ 綜合指數\t25,253.14\t+673.71\t+2.74%\t2026/11/09\t之下 季線 26,407.67\tFinMind`；`道瓊工業指數\t52,389.75\t+1,104.02\t+2.15%\t2026/11/09\t之上 季線 52,265.36\tFinMind`；`費城半導體指數\t10,033.93\t+643.68\t+6.85%\t2026/11/09\t之下 季線 11,686.06\tFinMind` |

### 新聞 `/news`：通過

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| N1 | 通過 | 6 張截圖 ready，無錯誤，無橫向捲動 |
| N2 | 通過 | domestic 前 3 則、international 前 3 則、official 前 3 則依序出現 |
| N3 | 通過 | 時間行 domestic 20／20、international 20／20、official 20／20 |
| N4 | 通過 | `AI 推論`／AI 判讀 domestic 20／20、international 20／20、official 10／10 |
| N5 | 通過 | 最新新聞 2026-11-10 09:50（台北）≤ 現在；國內第一則 `發布於 2026/11/10 09:44` |
| N6 | 通過 | id 26676：來源事實／AI 摘要與判讀分欄，`模型 claude-sonnet-5-5 · 提示版本 news_v3 · 產生時間 2026/11/10 10:01` |

### 族群 `/themes`：失敗

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| G1 | 失敗 | theme-detail-1280 未 ready；theme-detail-1280 httpErrors ['504 http://web:8080/api/news?theme_id=official-industry-206d1b19286222a7&limit=10', '504 http://web:8080/api/dashboard']；theme-detail-390 未 ready；theme-detail-390 httpErrors ['500 http://web:8080/api/dashboard', '504 http://web:8080/api/news?theme_id=official-industry-206d1b19286222a7&limit=10'] |
| G2 | 通過 | `產業榜 · 共 34 個族群` → `資料 2026/11/09`、`題材榜 · 共 12 個族群` → `資料 2026/11/09`；= facts 2026-11-09 |
| G3 | 通過 | 1280 與 390：`#1` → `食品`…`#34` → `電子零組件`，五分項與成員數同 API |
| G4 | 通過 | 20 個建議：`AI 推論` 20 行、沒有 `待核實`，`459 個建議` |
| G5 | 無法判定 | 無法判定：theme-detail-1280 未 ready |
| G6 | 無法判定 | 無法判定：theme-detail-1280 未 ready |
| G7 | 無法判定 | 無法判定：theme-detail-1280 未 ready |
| G8 | 無法判定 | 無法判定：theme-detail-1280 未 ready |

### 個股 `/stocks`：失敗

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| S1 | 失敗 | stocks-1280 未 ready；stocks-1280 httpErrors ['504 http://web:8080/api/stocks?page=1&page_size=30', '504 http://web:8080/api/dashboard']；stocks-390 未 ready；stocks-390 httpErrors ['504 http://web:8080/api/dashboard', '504 http://web:8080/api/stocks?page=1&page_size=30']；stock-1280 未 ready；stock-1280 httpErrors ['504 http://web:8080/api/dashboard']；stock-390 未 ready；stock-390 httpErrors ['504 http://web:8080/api/dashboard']；stock-financials-1280 未 ready；stock-financials-1280 httpErrors ['504 http://web:8080/api/dashboard']；stock-research-1280 未 ready；stock-research-1280 missingClicks ['#stock-tab-research']；stock-research-1280 httpErrors ['500 http://web:8080/api/stocks/TWSE/1216', '500 http://web:8080/api/stocks/TWSE/1216/bars?interval=day&limit=250', '504 http://web:8080/api/dashboard', '500 http://web:8080/api/dashboard', '504 http://web:8080/api/stocks/TWSE/1216']；stock-news-1280 未 ready；stock-news-1280 missingClicks ['#stock-tab-news']；stock-news-1280 httpErrors ['500 http://web:8080/api/dashboard', '504 http://web:8080/api/stocks/TWSE/1216', '500 http://web:8080/api/stocks/TWSE/1216', '504 http://web:8080/api/dashboard']；stock-data-1280 未 ready；stock-data-1280 missingClicks ['#stock-tab-data']；stock-data-1280 httpErrors ['500 http://web:8080/api/stocks/TWSE/1216', '500 http://web:8080/api/dashboard', '500 http://web:8080/api/stocks/TWSE/1216/bars?interval=day&limit=250', '500 http://web:8080/api/stocks/TWSE/1216/bars?interval=day&limit=250', '504 http://web:8080/api/stocks/TWSE/1216', '504 http://web:8080/api/dashboard'] |
| S2 | 無法判定 | 無法判定：stocks-1280 未 ready |
| S3 | 無法判定 | 無法判定：stock-1280 未 ready |
| S4 | 無法判定 | 無法判定：stock-1280 未 ready |
| S5 | 無法判定 | 無法判定：stock-research-1280 未 ready，missingClicks ['#stock-tab-research'] |
| S10 | 無法判定 | 無法判定：stock-research-1280 未 ready，missingClicks ['#stock-tab-research'] |
| S11 | 無法判定 | 無法判定：stock-1280 未 ready |
| S6 | 無法判定 | 無法判定：stock-news-1280 未 ready，missingClicks ['#stock-tab-news'] |
| S7 | 無法判定 | 無法判定：stock-data-1280 未 ready，missingClicks ['#stock-tab-data'] |
| S8 | 通過 | facts I 2026-11-09 = API；source `twse` |
| S9 | 通過 | 最新一列 2026/11/09；來源行 法人 30、融資 30 = min(30, 120) |
| S12 | 無法判定 | 無法判定：stock-financials-1280 未 ready |
| S13 | 無法判定 | 無法判定：stock-financials-1280 未 ready |

### 觀察中 `/watch`：失敗

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| A1 | 失敗 | actions-1280 未 ready；actions-1280 httpErrors ['500 http://web:8080/api/tracking?status=open&page=1&page_size=20', '500 http://web:8080/api/dashboard', '500 http://web:8080/api/tracking?status=closed&page=1&page_size=20', '504 http://web:8080/api/actions?view=focus&limit=20']；actions-390 未 ready；actions-390 httpErrors ['500 http://web:8080/api/portfolio?page=1&page_size=20', '500 http://web:8080/api/tracking?status=open&page=1&page_size=20', '500 http://web:8080/api/tracking?status=closed&page=1&page_size=20', '500 http://web:8080/api/actions?view=focus&limit=20', '500 http://web:8080/api/dashboard']；actions-legacy-1280 未 ready；actions-legacy-1280 httpErrors ['500 http://web:8080/api/tracking?status=open&page=1&page_size=20', '500 http://web:8080/api/portfolio?page=1&page_size=20', '500 http://web:8080/api/tracking?status=closed&page=1&page_size=20', '500 http://web:8080/api/actions?view=focus&limit=20', '504 http://web:8080/api/dashboard']；action-detail-1280 未 ready；action-detail-1280 httpErrors ['504 http://web:8080/api/dashboard'] |
| A2 | 無法判定 | 無法判定：actions-1280 未 ready |
| A3 | 無法判定 | 無法判定：actions-1280 未 ready |
| A4 | 無法判定 | 無法判定：actions-1280 未 ready |
| A5 | 無法判定 | 無法判定：actions-1280 未 ready |
| A6 | 無法判定 | 無法判定：action-detail-1280 未 ready |
| A7 | 無法判定 | 無法判定：action-detail-1280 未 ready |
| A8 | 無法判定 | 無法判定：actions-1280 未 ready |
| A9 | 無法判定 | 無法判定：actions-1280 未 ready |
| A10 | 無法判定 | 無法判定：actions-1280 未 ready |
| A11 | 無法判定 | 無法判定：actions-1280 未 ready |
| A12 | 無法判定 | 無法判定：actions-1280 未 ready |
| A13 | 無法判定 | 無法判定：actions-1280 未 ready |
| A14 | 無法判定 | 無法判定：actions-1280 未 ready |
| A15 | 無法判定 | 無法判定：actions-1280 未 ready |
| A16 | 無法判定 | 無法判定：actions-1280 未 ready |
| A17 | 無法判定 | 無法判定：actions-1280 未 ready |
| A18 | 無法判定 | 無法判定：actions-1280 未 ready |
