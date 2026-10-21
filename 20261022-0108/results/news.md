### 新聞 `/news`：通過

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| N1 | 通過 | 6 張截圖（news 1280／390、news-international 1280、news-official 1280、news-detail 1280／390）ready，無錯誤，無橫向捲動（shots/news.jsonl） |
| N2 | 通過 | 國內、國際、官方各 20 則；前 3 則標題依序整行出現（國內第 18／29／40 行、國際第 18／29／40 行、官方第 18／30／42 行；比對時全形空白正規化） |
| N3 | 通過 | 國內 20／20、國際 20／20、官方 20／20 張卡有時間行 |
| N4 | 通過 | 國內 `AI 推論` 20 行 = API done 且 inference 20 則；國際 20 = 20；官方 7 = 7 |
| N5 | 通過 | facts `news_latest_published_at` 2026-10-21 15:59（不晚於台北 2026-10-22 01:12）；國內第一則 `發布於 2026/10/21 23:32` 不晚於今天 |
| N6 | 通過 | `/news/1946`：`來源事實`、`AI 摘要與判讀` 整行出現，下一行 `AI 推論`；有 `模型 claude-haiku-5-5 · 提示版本 news_v1 · …` 行（390 寬同樣兩欄都在） |

另見（不影響判定）：詳情頁的模型行顯示 `產生時間 待核實`，API `ai.generated_at` 為 `2026-10-21T16:01:32.746332`（無時區）。

截圖：shots/news-1280.png、shots/news-390.png、shots/news-international-1280.png、shots/news-official-1280.png、shots/news-detail-1280.png、shots/news-detail-390.png
