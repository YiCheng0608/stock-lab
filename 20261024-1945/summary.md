## verify-stock-lab 真資料結果（2026-10-24 19:45 台北）

- 程式：`task/245-verify-plan` @ `a8b31fc`；工作樹另有未 commit 的 `.claude/skills/verify-stock-lab/SKILL.md`（只改文件，不影響建置）
- 副本：資料日 2026-10-22（`facts.json` 的 `market_latest_trading_date`），alembic `0016_group_score_archive`，複製 13.9 秒；非私人模式（`portfolio_positions` 0）
- 時段：使用者指示於 daily 時段內執行；副本最新的 `collect/official` 是 2026-10-23 的 `skipped`（颱風休市），沒有進行中的 run
- 證據：https://github.com/YiCheng0608/stock-lab/tree/pr-assets/245/20261024-1945
- 人工檢查：無（features 沒有標「人工」的檢查）

| 導覽 | 結果 | 失敗或無法判定的檢查（原因類別） |
| --- | --- | --- |
| 今日 `/` | 無法判定 | T2～T5：`dashboard.as_of`、`today-board.meta.trading_date` 為 null（產品缺陷，見下）；T6 已知失敗（#233），本次缺的是標題含 `\xa0` 的那一行（工具缺口，同 N2） |
| 新聞 `/news` | 失敗 | N2：id 2845 標題含 `\xa0 `，瀏覽器顯示成一個空白，`page_checks.normalize` 只處理半形與全形空白（工具缺口） |
| 族群 `/themes` | 失敗 | G2：兩榜顯示「資料日期待核實」、B 為 null（產品缺陷，見下）；G5～G7：today-board 為空 |
| 個股 `/stocks` | 無法判定 | S1～S9：today-board 為空（產品缺陷，見下） |
| 行動 `/actions` | 失敗 | A4：`actions.meta.data_as_of` 為 null（產品缺陷，見下）；A6、A7：today-board 為空 |

**產品缺陷（根因一個）**：`backend/app/decision.py` 的 `latest_official_run` 取最新一筆 `collect/official`，不看 status。2026-10-23 颱風休市那筆 run 是 `skipped`（`data_as_of` null），於是 `as_of` 變 null：族群榜回 `empty_reason=no_official_run`（「尚無成功的官方資料擷取」），今日、行動的資料日也是 null，雖然 10-22 的官方資料與族群分數都在。下一個交易日成功擷取後會自己恢復，但非交易日 run 存在期間頁面都是空的。

**工具缺口**：`tools/verify/page_checks.py` 的 `normalize` 沒把 U+00A0 當空白，造成 N2 與 T6 的比對失敗；另 SKILL 在 Windows 沒設 `PYTHONUTF8=1` 時 `page_checks.py` 印這則標題會 `UnicodeEncodeError`，起服務命令的 `$!` 抓到子 shell PID 導致 kill 沒關到服務，這兩點已在本 PR 的 SKILL 修正。

## verify 檢查結果（2026-10-24 19:48 台北）

- API `http://127.0.0.1:53414`、前端 `http://127.0.0.1:53415`、DB `stock.db`
- 38 項：通過 16、失敗 21、已知失敗 1；耗時 119 秒

### 今日 `/`：失敗

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| T1 | 通過 | 2 張截圖 ready，無錯誤，無橫向捲動 |
| T2 | 失敗 | 無法判定：dashboard.json 沒有 as_of（D） |
| T3 | 失敗 | 無法判定：dashboard.json 沒有 as_of（D） |
| T4 | 失敗 | 無法判定：today-board.json 沒有 meta.trading_date（B） |
| T5 | 失敗 | 無法判定：today-board.json 沒有 meta.trading_date（B） |
| T6 | 失敗（已知） | 缺新聞標題整行 `颱風假台股該不該開盤？政大教授點出交易真相  網友反問：誰要當韭菜`（id 2845）（已知：https://github.com/YiCheng0608/stock-lab/issues/233） |
| T7 | 通過 | `資料 2026/10/22`、`20 檔`；來源行 20 = items；C = facts |
| T8 | 通過 | 20 檔新聞情緒推論的來源行以 `（推論）` 結尾；`AI 推論` 20 行；免責句 20 行 |
| T9 | 通過 | 沒有卡片，顯示 `目前沒有資料完整的可執行條件；請查看缺少資料與補齊優先級` |

### 新聞 `/news`：失敗

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| N1 | 通過 | 6 張截圖 ready，無錯誤，無橫向捲動 |
| N2 | 失敗 | domestic：缺 `颱風假台股該不該開盤？政大教授點出交易真相  網友反問：誰要當韭菜`（news-1280.txt） |
| N3 | 通過 | 時間行 domestic 20／20、international 20／20、official 20／20 |
| N4 | 通過 | `AI 推論`／AI 判讀 domestic 20／20、international 20／20、official 20／20 |
| N5 | 通過 | 最新新聞 2026-10-24 16:45（台北）≤ 現在；國內第一則 `發布於 2026/10/24 16:45` |
| N6 | 通過 | id 2845：來源事實／AI 摘要與判讀分欄，`模型 claude-haiku-5-5 · 提示版本 news_v1` |

### 族群 `/themes`：失敗

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| G1 | 通過 | 3 張截圖 ready，無錯誤，無橫向捲動 |
| G2 | 失敗 | `產業榜 · 共 0 個族群` 下一行是 '資料日期待核實'，預期 `資料 `（themes-1280.txt 第 15 行）；產業榜 B None ≠ facts 2026-10-22；`題材榜 · 共 0 個族群` 下一行是 '資料日期待核實'，預期 `資料 `（themes-theme-1280.txt 第 15 行）；題材榜 B None ≠ facts 2026-10-22 |
| G3 | 通過 | items 空，顯示 `尚無成功的官方資料擷取，無法提供族群榜。` |
| G4 | 通過 | 20 個建議：`待核實` 20、`AI 推論` 20 行，`587 個建議` |
| G5 | 失敗 | 無法判定：today-board.json 的 items 為空（T） |
| G6 | 失敗 | 無法判定：today-board.json 的 items 為空（T） |
| G7 | 失敗 | 無法判定：today-board.json 的 items 為空（T） |

### 個股 `/stocks`：失敗

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| S1 | 失敗 | 無法判定：today-board.json 的 items 為空（T） |
| S2 | 失敗 | 無法判定：today-board.json 的 items 為空（T） |
| S3 | 失敗 | 無法判定：today-board.json 的 items 為空（T） |
| S4 | 失敗 | 無法判定：today-board.json 的 items 為空（T） |
| S5 | 失敗 | 無法判定：today-board.json 的 items 為空（T） |
| S6 | 失敗 | 無法判定：today-board.json 的 items 為空（T） |
| S7 | 失敗 | 無法判定：today-board.json 的 items 為空（T） |
| S8 | 失敗 | 無法判定：today-board.json 的 items 為空（T） |
| S9 | 失敗 | 無法判定：today-board.json 的 items 為空（T） |

### 行動 `/actions`：失敗

| 檢查 | 結果 | 證據 |
| --- | --- | --- |
| A1 | 通過 | 2 張截圖 ready，無錯誤，無橫向捲動 |
| A2 | 通過 | 沒有庫存，顯示 `尚未建立庫存。` |
| A3 | 通過 | `第 1 頁 · 本頁 3 筆 · 共 3 筆` |
| A4 | 失敗 | actions.json 沒有 meta.data_as_of |
| A5 | 通過 | 沒有 `AI 推論` 與 `（推論）` |
| A6 | 失敗 | 無法判定：today-board.json 的 items 為空（T） |
| A7 | 失敗 | 無法判定：today-board.json 的 items 為空（T） |
