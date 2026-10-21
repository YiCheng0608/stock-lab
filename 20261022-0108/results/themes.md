### 族群 `/themes`：通過

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| G1 | 通過 | 5 張截圖（themes 1280／390、themes-theme 1280、theme-detail 1280／390）ready，無錯誤，無橫向捲動（shots/themes.jsonl） |
| G2 | 通過 | `產業榜 · 共 34 個族群` 下一行 `資料 2026/10/21`（themes-1280.txt 第 15～16 行）；`題材榜 · 共 12 個族群` 下一行 `資料 2026/10/21`（themes-theme-1280.txt 第 15～16 行）；兩榜 `trading_date` = `data_as_of` = facts 2026-10-21 |
| G3 | 通過 | 兩榜皆有 `排名\t族群…` 表頭；產業 `鋼鐵`／`電子通路`、題材 items[0]／`CoWoS 先進封裝` 皆整行出現；390 寬 `#1` 下一行 `鋼鐵` |
| G4 | 通過 | 12 則建議；整行 `待核實` 20 行、`AI 推論` 20 行，皆 ≥ 12；`433 個建議 · 最近更新 2026/10/21 21:36` 存在（meta.total 433） |
| G5 | 通過 | `熱度走勢`、`五分項` 下一行皆 `資料 2026/10/21`（theme-detail-1280.txt 第 25～26、53～54 行）；`成員資料截至 2026/10/21`（第 71 行，M = 2026-10-21） |
| G6 | 通過 | 成員表頭整行存在；第一個成員 `3004	豐達科	上市	成員	123	2026/10/21`（第 77 行）；`第 1／2 頁 · 共 48 檔`（第 107 行） |
| G7 | 通過 | 今日 #1 `鋼鐵` = 產業榜 items[0] `鋼鐵` = 詳情 `theme.display_name` `鋼鐵`（theme_id `official-industry-b597d5609a60578d`） |

截圖：shots/themes-1280.png、shots/themes-390.png、shots/themes-theme-1280.png、shots/theme-detail-1280.png、shots/theme-detail-390.png
