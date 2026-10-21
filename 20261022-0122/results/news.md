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
