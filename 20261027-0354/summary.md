## verify-stock-lab 真資料結果：正式 run（2026-10-27 04:00 台北）

- 程式：`task/306-v11-real-verify` @ `72f5529`（= `origin/master`，工作樹乾淨、無額外 commit；不加 `--g7`）
- 副本：資料日 2026-10-22（`copy.json` 的 `source_latest_trading_date`），alembic 複製時 `0017_tracking_plans`，只對副本 `init-db` 升到 `0020_trading_calendar`，複製 12.3 秒
- 結果：`page_checks.py` exit 1，在 today T2 呼叫 `db_facts.facts()` 時 `TypeError: 'NoneType' object is not subscriptable`（`db_facts.py:111`；`candidate_count_latest` 查 `candidate_score_v2`，副本只有 `candidate_score_v1` 的 run），沒有寫出 `results.json`／`summary.md`／人工樣本；`facts.json` 為空（同一個錯）。完整 traceback 在 `checks.log`。
- 五個導覽：今日、新聞、族群、個股、行動全部 **無法判定**（工具缺口，#307）。

依 features「不改檢查讓它通過」，本輪不改工具；另做一次「補充 run」（只在 worktree 外的包裝程式把這一條查詢改成查不到時回 NULL，repo 檔案不動），結果在 `../20261027-0354-supplementary/summary.md`，不取代本結果。
