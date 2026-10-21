### 新聞 `/news`：通過

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| N1 | 通過 | 6 張截圖（news 1280／390、news-international 1280、news-official 1280、news-detail 1280／390）ready，httpErrors、consoleErrors 皆空，無橫向捲動 |
| N2 | 通過 | 國內前 3 則標題依序為 news-1280.txt 第 19、30、41 行；國際前 3 則依序為 news-international-1280.txt 第 19、30、41 行；官方 API 標題含 `\r\n`（頁面顯示為空白），改比來源標籤與時間：前 3 張卡依序為 `公開資訊觀測站公告`（`source_name` MOPS）＋ `事件日 2026/10/20`（= `event_date` 2026-10-20），第 17／23、29／35、41／47 行 |
| N3 | 通過 | 時間行：國內 20／20、國際 20／20、官方 20／20 |
| N4 | 通過 | 整行 `AI 推論`：國內 20 = API done 20、國際 20 = 20、官方 7 = 7 |
| N5 | 通過 | facts `news_latest_published_at` 2026-10-21 15:59 UTC → 23:59 台北，早於現在 2026-10-22 01:41；國內第一則時間行 `發布於 2026/10/21 23:32`（第 23 行）不晚於今天 |
| N6 | 通過 | news-detail（id 1946）：第 11 行 `來源事實`、第 28 行 `AI 摘要與判讀` → 第 29 行 `AI 推論`；ai done，第 49 行以 `模型 claude-haiku-5-5 · 提示版本 news_v1` 開頭（產生時間顯示 `待核實`，`ai.generated_at` 無時區，依前端規則不顯示） |

截圖：shots/news-1280.png、shots/news-390.png、shots/news-international-1280.png、shots/news-official-1280.png、shots/news-detail-1280.png、shots/news-detail-390.png
