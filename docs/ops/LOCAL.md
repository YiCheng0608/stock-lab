<!-- owns: 本機路徑 -->
# 本機路徑

這台主機上的實際路徑只寫在本文；其他文件與 skill 以名稱（例如「正式資料目錄」「發佈 checkout」）引用這裡。

## 正式位置（使用者決定）

使用者 2026-10-17 決定（[#1](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-6235674933)），用途見[排程](SCHEDULING.md)與 [daily／news 工作的註冊與管理](platform/windows.md#dailynews-工作的註冊與管理)：

| 名稱 | 路徑 |
| --- | --- |
| 正式資料目錄 | `C:/Users/YiCheng/stock-lab-data/`（`stock.db`、`raw/`、`logs/`） |
| 正式 DB | `C:/Users/YiCheng/stock-lab-data/stock.db` |
| 統籌的資料目錄的 `logs/`（正式 scheduler 的 `STOCK_COORDINATION_DIR`，[統籌事件 monitor](MONITOR.md)） | `C:/Users/YiCheng/stock-lab-data/logs` |
| 發佈 checkout | `C:/Users/YiCheng/stock-lab-release/` |
| 發佈 checkout 的 venv | `C:/Users/YiCheng/stock-lab-release/.venv`（套件在 `.venv/Lib/site-packages`） |
| 含 migration 的部署前備份（[RELEASE](../RELEASE.md#含-migration-的版本)） | `C:/Users/YiCheng/stock-lab-backup/<YYYYMMDD>-before-<tag>/stock.db` |

## 工具

| 名稱 | 路徑 |
| --- | --- |
| 容器外的 Python（PATH 上的 python 是 Store stub） | `C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe` |
| codebase-memory 同引擎 CLI | `C:/Users/YiCheng/.local/bin/codebase-memory-mcp.cmd` |
| worktree 外暫存目錄 | `C:/Users/YiCheng/t<issue>` |
