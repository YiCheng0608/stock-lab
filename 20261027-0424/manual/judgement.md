判讀者：獨立 session（subagent），輸出目錄 C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/task-308-hide-stale-news-ai/.local/verify/out/20261027-0424

| 檢查 | 樣本 id | 結果 | 證據 |
| --- | --- | --- | --- |
| T10 | —（0 筆） | 無法判定 | `manual/T10.json` 的 `items` 為 0 筆、`trading_date` 為 null，rule「candidates.json 依名次前 3 檔」；`facts.json` 的 `candidate_run_latest_trading_date` 與 `candidate_count_latest` 皆為 null（副本沒有候選 run） |
| N7 | —（0 筆） | 無法判定 | `manual/N7.json` 的 `items` 為 0 筆，rule「/news?category=domestic&limit=100（依 next_cursor 往後最多 5 頁）中台北發布日 = D（2026-10-22）且有 AI 判讀的前 5 則，API 順序」；檔內無 `error` |
| N8 | —（0 筆） | 無法判定 | `manual/N8.json` 的 `items` 為 0 筆，rule 與 N7 相同（台北發布日 = 2026-10-22 且有 AI 判讀的前 5 則）；檔內無 `error` |
