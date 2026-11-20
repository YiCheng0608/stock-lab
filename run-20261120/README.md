# #875 AC-3：H2 前瞻入口在正式 DB 唯讀副本上的試跑

- 副本：`tools/ops/copy_db.py` 從 `stock-lab_stock-data:/data:ro` 複製到 Docker volume `task-875_db`（image `stock-lab-backend:v1.2.71`），`quick_check` ok，4,113,436,672 bytes，130 秒。
- 資料日期：副本最新交易日 2026-11-20，alembic `0033_mainstream_lists`。
- 命令（evidence.md「每月流程」第 3 步，H2 那一行；工具 commit `68d1fcfd`，compose project `task-875`）：
  `python tools/research/forward_watch.py --db /db/stock.db --watch H2 --out /out/H2 --min-free-gb 0`
- 結果：`{"watch": "H2", "days": 0, "min_days": 60, "verdict": "樣本不足", "elapsed_seconds": 18.3}`，峰值記憶體 0.30 GB。
  前瞻起日 2026-11-20 正好是副本最後一個交易日，訊號日要在 cutoff 的前一個交易日以前，所以還沒有訊號日與淨值，輸出「樣本不足（累積 0／60 日）」。
- `H2/raw/` 是空目錄，沒有推。
