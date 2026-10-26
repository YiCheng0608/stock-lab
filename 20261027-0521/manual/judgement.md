# 人工檢查判讀（20261027-0521，#307 AC-4、#306 重跑）

判讀 session 只讀 `manual/T10.json`、`N7.json`、`N8.json` 與同目錄 `api/`、`summary.md`；未改程式、資料或 git 狀態，未對 API 送請求。三個檔都沒有 `error` 欄位，`items` 都是 0 筆，依 SKILL 真資料模式第 3 步記無法判定。

| 檢查 | 樣本 id | 結果 | 證據 |
| --- | --- | --- | --- |
| T10 | —（0 筆） | 無法判定 | `rule`：`candidates.json 依名次前 3 檔`，`items` 0 筆、`trading_date` null；`api/candidates.json` 為 `status: not_computed`、`candidate_count: 0`（summary T7：DB 也沒有當日候選） |
| N7 | —（0 筆） | 無法判定 | `rule`：`/news?category=domestic&limit=100（依 next_cursor 往後最多 5 頁）中台北發布日 = D（2026-10-22）且有 AI 判讀的前 5 則，API 順序`，`items` 0 筆；`api/news-domestic-100-1.json`～`-4.json` 台北發布日都在 2026-10-23 之後，`-5.json` 有 97 則台北發布日 2026-10-22，但 100 則的 `ai` 都是 null（無目前提示版本 `news_v2` 的 done 結果），沒有符合條件的樣本 |
| N8 | —（0 筆） | 無法判定 | `rule` 同 N7，`items` 0 筆；樣本來源同 N7，原因相同 |
