## verify 檢查結果（2026-10-27 01:14 台北）

- 程式：`task/300-mobile-layout` @ `e7b25d4`（未 commit：.claude/skills/verify-stock-lab/features/stocks.md、.claude/skills/verify-stock-lab/features/themes.md、docs/DESIGN_SYSTEM.md、docs/UI_COPY_SPEC.md、frontend/src/App.tsx、frontend/src/components/ui/index.ts、frontend/src/news/news.test.tsx、frontend/src/stock/stockBars.test.tsx、frontend/src/styles.css、frontend/src/tables.test.tsx、frontend/src/themes/ThemeViews.tsx、frontend/src/themes/themeBoards.test.tsx、frontend/src/components/ui/CardList.tsx、frontend/src/stock/StockCutoffControl.tsx）
- API `http://127.0.0.1:18300`、前端 `http://127.0.0.1:14303`、DB `stock.db`（假資料庫）
- 個股 E／S：TWSE 9101，今日榜 #1 族群「半導體」的第一個成員
- 59 項：通過 59、失敗 0、無法判定 0、已知失敗 0；耗時 54 秒

### 人工檢查樣本（依 features 規則抽樣，判讀見 SKILL 真資料模式第 3 步）

| 檢查 | 樣本 |
| --- | --- |
| T10 | 3 筆，`manual/T10.json` |
| N7 | 1 筆，`manual/N7.json` |
| N8 | 1 筆，`manual/N8.json` |

### 今日 `/`：通過

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| API | 通過 | 25 項 = fixture_data.EXPECTED |
| T1 | 通過 | 2 張截圖 ready，無錯誤，無橫向捲動 |
| T2 | 通過 | `資料 2026/10/16` = facts 2026-10-16 |
| T3 | 通過 | `資料截至 2026/10/16 · TWSE／TPEx 官方資料 · 官方單日快照` |
| T4 | 通過 | `資料 2026/10/16`；B = facts 2026-10-16 |
| T5 | 通過 | 2 張卡 `資料 2026/10/16 · 相對加權指數`；#1 `半導體` |
| T6 | 通過 | 前 3 則標題都在；有 AI 判讀的卡片方向與 AI 相同並標 `AI 推論`：1 `可能正向`、5 `可能負向` |
| T7 | 通過 | `資料 2026/10/16`、`3 檔`；名次列 3、來源行 3 = items；C = facts |
| T8 | 通過 | 3 檔新聞情緒推論的來源行以 `（推論）` 結尾；`AI 推論` 5 行；免責句 3 行；入口 `AI 推論 ▸` 3、`AI 說明 ▸` 0 |
| T9 | 通過 | 6 張卡各有 `資料日` |
| T11 | 通過 | 2026-10-16：TWSE 24,012.35、TPEx 251.20；範圍 `上市為集中市場總計（含 ETF、權證等）；上櫃為上櫃股票` |
| T12 | 通過 | `明日候選`（today-1280.txt 第 33 行）→ `熱門族群`（today-1280.txt 第 157 行）、`重點新聞`（today-1280.txt 第 187 行） |

### 新聞 `/news`：通過

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| API | 通過 | 9 項 = fixture_data.EXPECTED |
| N1 | 通過 | 6 張截圖 ready，無錯誤，無橫向捲動 |
| N2 | 通過 | domestic 前 3 則、international 前 2 則、official 前 1 則依序出現 |
| N3 | 通過 | 時間行 domestic 3／3、international 2／2、official 1／1 |
| N4 | 通過 | `AI 推論`／AI 判讀 domestic 2／2、international 2／2、official 0／0 |
| N5 | 通過 | 最新新聞 2026-10-16 09:30（台北）≤ 現在；國內第一則 `發布於 2026/10/16 09:30` |
| N6 | 通過 | id 1：來源事實／AI 摘要與判讀分欄，`模型 claude-sonnet-5-5 · 提示版本 news_v2 · 產生時間 2026/10/16 11:01` |

### 族群 `/themes`：通過

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| API | 通過 | 14 項 = fixture_data.EXPECTED |
| G1 | 通過 | 5 張截圖 ready，無錯誤，無橫向捲動 |
| G2 | 通過 | `產業榜 · 共 2 個族群` → `資料 2026/10/16`、`題材榜 · 共 2 個族群` → `資料 2026/10/16`；= facts 2026-10-16 |
| G3 | 通過 | 1280 表頭與 `半導體`…`電腦及週邊`；390 `#1` → `半導體` |
| G4 | 通過 | 2 個建議：`待核實` 2、`AI 推論` 2 行，`2 個建議` |
| G5 | 通過 | 熱度走勢、五分項皆 `資料 2026/10/16`；`成員資料截至 2026/10/16` |
| G6 | 通過 | 表頭、第一個成員 9101 示範晶圓、`共 3 檔` |
| G7 | 通過 | 今日 #1 = 產業榜 #1 = 詳情 = `半導體` |
| G8 | 通過 | 成員依成交值：9101、9102、9201 |

### 個股 `/stocks`：通過

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| API | 通過 | 21 項 = fixture_data.EXPECTED |
| S1（TWSE 9101） | 通過 | 8 張截圖 ready，無錯誤，無橫向捲動 |
| S1（TPEx 9204） | 通過 | 6 張截圖 ready，無錯誤，無橫向捲動 |
| S2 | 通過 | 表頭、第一列、`第 1／1 頁 · 共 8 筆` |
| S3（TWSE 9101） | 通過 | 頁首 `資料 2026/10/16`、`來源 臺灣證券交易所`；bars data_as_of 2026-10-16 |
| S3（TPEx 9204） | 通過 | 頁首 `資料 2026/10/16`、`來源 證券櫃檯買賣中心`；bars data_as_of 2026-10-16 |
| S4（TWSE 9101） | 通過 | K 線卡 `資料 2026/10/16`、來源與批次時間 |
| S4（TPEx 9204） | 通過 | K 線卡 `資料 2026/10/16`、來源與批次時間 |
| S5（TWSE 9101） | 通過 | `資料日期：2026/10/16`、`資料日：2026/10/16 · 價位語意：`；候選 #1：`每日候選`、`AI 推論`、`（推論）` |
| S5（TPEx 9204） | 通過 | `資料日期：2026/10/16`、`資料日：2026/10/16 · 價位語意：` |
| S10（TWSE 9101） | 通過 | `策略總表` 資料 2026-10-16；突破條件 成立、回踩條件 觀察；觀察價位 1 列；候選第 1 名 |
| S10（TPEx 9204） | 通過 | `策略總表` 資料 2026-10-16；突破條件 資料不足、回踩條件 資料不足；觀察價位 0 列；非候選 |
| S6（TWSE 9101） | 通過 | 1 則相符新聞，時間行 1 |
| S6（TPEx 9204） | 通過 | 0 則相符新聞，顯示 `尚無與此股已核實關聯的新聞或公告。` |
| S7（TWSE 9101） | 通過 | K 線資料日期 2026/10/16、行情來源 `臺灣證券交易所`、`…資料日 2026/10/16` |
| S7（TPEx 9204） | 通過 | K 線資料日期 2026/10/16、行情來源 `證券櫃檯買賣中心`、`…資料日 2026/10/16` |
| S8（TWSE 9101） | 通過 | facts I 2026-10-16 = API；source `twse` |
| S8（TPEx 9204） | 通過 | facts I 2026-10-16 = API；source `tpex` |
| S9（TWSE 9101） | 通過 | 最新一列 2026/10/16；來源行 25 = min(30, 25) |
| S9（TPEx 9204） | 通過 | chips 空，顯示 `尚無可核實的籌碼資料。` |

### 行動 `/actions`：通過

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| API | 通過 | 14 項 = fixture_data.EXPECTED |
| A1 | 通過 | 3 張截圖 ready，無錯誤，無橫向捲動 |
| A2 | 通過 | 1 筆庫存各有 `記錄來源` |
| A3 | 通過 | 持倉風險 `顯示 1／1 檔`；今日候選 `顯示 3／3 檔` |
| A4 | 通過 | 4 列各有資料日 ≤ 2026/10/16；data_as_of = facts |
| A5 | 通過 | 4 列，沒有 `AI 推論` 與 `（推論）` |
| A6 | 通過 | TWSE 9101：`資料日：2026/10/16` = data_cutoff |
| A7 | 通過 | 頁首 `9101`／`示範晶圓` = stock.json |
| A8 | 通過 | 今日候選 3 列 = candidates.json 去掉持倉，依名次 [1, 2, 3] |
| A9 | 通過 | 預設清單沒有 ETF（持倉／自選 ETF 0 列）；隱藏 ETF 1 檔 |
| A10 | 通過 | `預設隱藏：ETF 1 檔、其他觀察 2 檔；自選標的一律顯示。隱藏不刪資料，切換上方篩選即可看到。` |
