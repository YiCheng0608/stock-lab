# #868 AC-3 試跑：X4 前瞻入口，正式 DB 唯讀副本（2026-11-20）

- 工具：`tools/research/forward_watch.py`，branch `task/868-forward-watch-x4` 的 `320f5c30`（`tables.json` 的 `tool_commit`）
- 副本：`copy_db.py` 從 `stock-lab_stock-data` 唯讀複製到 Docker volume `task-868_copy`；`source_latest_trading_date` 2026-11-19，alembic `0033_mainstream_lists`，`quick_check` ok，4,036,980,736 bytes，38.6 秒
- 命令（image `stock-lab-backend:v1.2.71`，worktree 唯讀掛在 `/app`，副本唯讀掛在 `/copy`，`--network none`；主機空閒記憶體 10.3 GB）：
  `python -B tools/research/forward_watch.py --db /copy/stock.db --watch X4 --out /out/X4 --min-free-gb 0`
- 結果：`{"watch": "X4", "days": 0, "min_days": 60, "verdict": "樣本不足", "elapsed_seconds": 11.9}`，峰值記憶體 0.30 GB
- 解讀：副本的資料到 2026-11-19，前瞻起日 2026-11-20 以後還沒有交易日，所以累積 0 日、「樣本不足（累積 0／60 日）」（AC-3 允許）。第一個訊號日是 2026-11-20，第一筆淨值是下一個交易日。
- `X4/raw/`（除權息的原始檔）沒有推上來。
