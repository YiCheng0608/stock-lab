## verify-stock-lab 結果（2026-10-22 01:22 台北）

- 程式：`task/227-verify-skill` @ `445533a`（工作樹含未 commit 改動 `frontend/src/themes/ThemeViews.tsx`，照現狀建置）
- 副本：資料日 2026-10-21（`market_bars` 最新），alembic `0016_group_score_archive`，複製 6.1 秒
- Doctor：health 200、readiness 通過、proxy 200
- 證據：https://github.com/YiCheng0608/stock-lab/tree/pr-assets/227/20261022-0122

| 導覽 | 結果 | 失敗或無法判定的檢查 |
| --- | --- | --- |
| 今日 `/` | 失敗 | T6：前 3 則新聞 `/api/news/1958`、`/1952`、`/1946` 皆有 AI 判讀（done、inference true），今日卡全部顯示 `影響尚未判定`、無 `AI 推論`（today-1280.txt 第 25～53 行）；`/api/dashboard` 的 `news` 項目沒有 `ai` 欄位、`impact_direction` 為 `unknown` |
| 新聞 `/news` | 通過 | — |
| 族群 `/themes` | 失敗 | G2：產業榜與題材榜缺資料日期標記（預期 `資料 2026/10/21`；themes-1280.txt 第 15 行 `產業榜 · 共 34 個族群`、themes-theme-1280.txt 第 15 行 `題材榜 · 共 12 個族群` 的下一行都是空白與表格說明，全檔沒有該行） |
| 個股 `/stocks` | 通過 | — |
| 行動 `/actions` | 通過 | — |

路徑：今日 #1 產業「鋼鐵」→ 族群詳情 → 個股 TWSE 3004 → 行動 TWSE 3004。
耗時：Launch 0:29、Doctor 0:11、Drive 9:36。

### 今日 `/`：失敗

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| T1 | 通過 | 1280／390 ready，無 console／HTTP 錯誤，無橫向捲動 |
| T2 | 通過 | `資料 2026-10-21`（today-1280.txt 第 7 行）；facts market_latest_trading_date 2026-10-21 |
| T3 | 通過 | `資料截至` 第 13 行，下一行 `2026/10/21`（預期 `2026/10/21`），再下一行 `TWSE／TPEx 官方資料`（source_label `TWSE／TPEx 官方資料`） |
| T4 | 通過 | `熱門族群` 第 54 行後第一個資料行 `資料 2026/10/21`（第 58 行）；B 2026-10-21，facts group_scores 2026-10-21 |
| T5 | 通過 | 卡片日期行 10 = min(10, 10)；#1 `鋼鐵` 第 60 行 |
| T6 | 失敗 | #1958「Polymarket trade…」`/api/news/1958` ai done／inference true（negative），卡片（第 25～34 行）顯示 `影響尚未判定`、無 `AI 推論`；#1952「How Ukraine’s dr…」`/api/news/1952` ai done／inference true（negative），卡片（第 35～44 行）顯示 `影響尚未判定`、無 `AI 推論`；#1946「台股反彈594點！分析師拋「4萬…」`/api/news/1946` ai done／inference true（positive），卡片（第 45～53 行）顯示 `影響尚未判定`、無 `AI 推論` |
| T7 | 通過 | `明日候選` 第 180 行下接 `資料 2026/10/21`、`20 檔`；`^來源：` 20 行 = items 20；C 2026-10-21 = facts 2026-10-21 |
| T8 | 通過 | news_sentiment.inference true 20 檔，來源行結尾（推論）缺 0；整行 `AI 推論` 20 ≥ 20；免責句 20 = 20 |
| T9 | 通過 | `查看個股詳情 →` 6 行，`資料日 YYYY/MM/DD` 6 行 |

截圖：shots/today-1280.png、shots/today-390.png

### 新聞 `/news`：通過

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| N1 | 通過 | 6 張截圖 ready，無 console／HTTP 錯誤，無橫向捲動 |
| N2 | 通過 | 國內 前 3 則標題依序整行出現（第19行、第30行、第41行）；國際 前 3 則標題依序整行出現（第19行、第30行、第41行）；官方 前 3 則標題依序整行出現（第19行、第31行、第43行） |
| N3 | 通過 | 時間行：國內 20／20、國際 20／20、官方 20／20 張卡 |
| N4 | 通過 | 國內 `AI 推論` 20 行 vs API done 20 則；國際 `AI 推論` 20 行 vs API done 20 則；官方 `AI 推論` 7 行 vs API done 7 則 |
| N5 | 通過 | news_latest_published_at UTC 2026-10-21 15:59 → 台北 2026-10-21 23:59 ≤ 現在 2026-10-22 01:26；國內第一則 `發布於 2026/10/21 23:32` ≤ 2026-10-22 |
| N6 | 通過 | news/1946：`來源事實` 第 11 行、`AI 摘要與判讀` 第 28 行下接 `AI 推論`；`模型 claude-haiku-5-5 · 提示版本 news_v1` 開頭行在第 49 行 |

截圖：shots/news-1280.png、shots/news-390.png、shots/news-international-1280.png、shots/news-official-1280.png、shots/news-detail-1280.png、shots/news-detail-390.png

### 族群 `/themes`：失敗

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| G1 | 通過 | 5 張截圖 ready，無 console／HTTP 錯誤，無橫向捲動 |
| G2 | 失敗 | themes-1280.txt：`產業榜 · 共 34 個族群`（第 15 行）下一行為空白，預期 `資料 2026/10/21`（全檔 `資料 2026/10/21` 整行出現於 無；第 16～17 行為空白與表格說明）；themes-theme-1280.txt：`題材榜 · 共 12 個族群`（第 15 行）下一行為空白，預期 `資料 2026/10/21`（全檔 `資料 2026/10/21` 整行出現於 無；第 16～17 行為空白與表格說明）；B 2026-10-21 = facts 2026-10-21 |
| G3 | 通過 | 1280 表頭 `排名\t族群…` 第 19 行；首 `鋼鐵` 第 21 行、末 `電子通路` 第 120 行；390 `#1` 第 10 行下接 `鋼鐵` |
| G4 | 通過 | 整行 `待核實` 20 ≥ 20、`AI 推論` 20 ≥ 20；`433 個建議 · 最近更新 2026/10/21 21:36`（第 124 行） |
| G5 | 通過 | `熱度走勢`（第 25 行）下接 `資料 2026/10/21`、`五分項`（第 53 行）下接 `資料 2026/10/21`；`成員資料截至 2026/10/21` 第 71 行 |
| G6 | 通過 | 表頭第 76 行；`3004 豐達科` 同列第 77 行；`第 1／2 頁 · 共 48 檔` 第 107 行 |
| G7 | 通過 | 今日 #1 `鋼鐵`（today-1280.txt 第 60 行）= 產業榜 items[0] `鋼鐵` = 詳情 theme.display_name `鋼鐵`（theme-detail-1280.txt 第 12 行） |

截圖：shots/themes-1280.png、shots/themes-390.png、shots/themes-theme-1280.png、shots/theme-detail-1280.png、shots/theme-detail-390.png

### 個股 `/stocks`：通過（TWSE 3004 豐達科）

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| S1 | 通過 | 7 張截圖 ready，missingClicks 空，無 console／HTTP 錯誤，無橫向捲動 |
| S2 | 通過 | 表頭第 22 行；`00411A` 開頭列第 23 行；`第 1／81 頁 · 共 2,410 筆` 第 53 行 |
| S3 | 通過 | 整行 `3004` 第 9 行；第一個資料行 `資料 2026-10-21`（第 7 行，導覽列），第二個 `資料 2026-10-21`（第 16 行）下接 `來源 臺灣證券交易所`；bars data_as_of 2026-10-21 |
| S4 | 通過 | `K 線與技術指標` 第 28 行下接 `資料 2026-10-21`；`來源 臺灣證券交易所` 第 41 行；`日線批次計算於 2026-10-21 21:35（台灣時間）` 第 43 行 |
| S5 | 通過 | `研究動作` 第 27 行；`資料日期：2026/10/21…` 第 33 行、`資料日：2026/10/21 · 價位語意：…` 第 35 行；candidate null（不在最新候選），略過候選標記 |
| S6 | 通過 | `3004 相關新聞` 第 28 行；API 0 則、相符 0 則，空狀態第 31 行 |
| S7 | 通過 | `K 線資料日期` 第 78 行下接 `2026-10-21`；`行情來源` 第 68 行下接 `臺灣證券交易所`；`行情來源完整 · 資料日 2026/10/21` 第 46 行 |
| S8 | 通過 | bars data_as_of 2026-10-21 = facts-stock latest_trading_date 2026-10-21；source `twse` |

截圖：shots/stocks-1280.png、shots/stocks-390.png、shots/stock-1280.png、shots/stock-390.png、shots/stock-research-1280.png、shots/stock-news-1280.png、shots/stock-data-1280.png

### 行動 `/actions`：通過

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| A1 | 通過 | 3 張截圖 ready，missingClicks 空，無 console／HTTP 錯誤，無橫向捲動 |
| A2 | 通過 | `我的庫存` 第 24 行；portfolio items 0，`尚未建立庫存。` 第 39 行 |
| A3 | 通過 | `第 1 頁 · 本頁 20 筆 · 共 1,858 筆` 第 206 行 |
| A4 | 通過 | 20 張卡、20 行 `資料日 YYYY/MM/DD`（2026/10/21），晚於 2026/10/21 的 0 行；data_as_of 2026-10-21 = facts 2026-10-21 |
| A5 | 通過 | actions-1280.txt 無 `推論` |
| A6 | 通過 | 整行 `3004` 第 9 行、`研究動作` 第 27 行（下接 `暫無研究條件`）；`資料日：2026/10/21`（第 35 行）= data_cutoff 2026/10/21 |
| A7 | 通過 | action-detail 頁首 `3004`／`豐達科`（第 9～10 行）= stock.json `3004`／`豐達科` |

截圖：shots/actions-1280.png、shots/actions-390.png、shots/action-detail-1280.png

