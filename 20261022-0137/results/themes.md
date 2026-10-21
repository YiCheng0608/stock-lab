### 族群 `/themes`：通過

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| G1 | 通過 | 5 張截圖（themes 1280／390、themes-theme 1280、theme-detail 1280／390）ready，httpErrors、consoleErrors 皆空，無橫向捲動 |
| G2 | 通過 | themes-1280.txt 第 15 行 `產業榜 · 共 34 個族群` → 第 16 行 `資料 2026/10/21`；themes-theme-1280.txt 第 15 行 `題材榜 · 共 12 個族群` → 第 16 行 `資料 2026/10/21`；B 2026-10-21 = facts `group_scores_latest_trading_date`（data_as_of 與 trading_date 相同，無 `官方資料` 行） |
| G3 | 通過 | 兩榜第 20 行表頭以 `排名\t族群` 開頭；產業榜首「鋼鐵」第 22 行、末「電子通路」第 121 行；題材榜首「金控」第 22 行、末「CoWoS 先進封裝」第 55 行；themes-390.txt 第 11 行 `#1` → 第 12 行「鋼鐵」 |
| G4 | 通過 | 建議 20 則：整行 `待核實` 20 行、`AI 推論` 20 行；第 125 行 `433 個建議 · 最近更新 2026/10/21 21:36` |
| G5 | 通過 | theme-detail-1280.txt 第 25 行 `熱度走勢` → `資料 2026/10/21`、第 53 行 `五分項` → `資料 2026/10/21`；第 71 行 `成員資料截至 2026/10/21`（M = members `data_as_of` 2026-10-21） |
| G6 | 通過 | 第 76 行表頭 `代號\t名稱\t市場\t角色\t收盤\t資料日期`；第 77 行 `3004\t豐達科\t上市\t成員\t123\t2026/10/21`；第 107 行 `第 1／2 頁 · 共 48 檔`（48 檔、每頁 30） |
| G7 | 通過 | 今日 `#1`「鋼鐵」（today-1280.txt 第 60 行）= 產業榜 `items[0].display_name`「鋼鐵」= 詳情 `theme.display_name`「鋼鐵」（theme-detail-1280.txt 第 12 行） |

截圖：shots/themes-1280.png、shots/themes-390.png、shots/themes-theme-1280.png、shots/theme-detail-1280.png、shots/theme-detail-390.png
