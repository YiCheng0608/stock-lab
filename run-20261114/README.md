# #691 AC-3 試跑（2026-11-14）

- 工具：`task/691-forward-h1` 的 `1b42e41`（H1 凍結的 commit）；副本：正式 volume 以 `copy_db.py` 複製到任務 volume `task-691_db`，最新交易日 2026-11-13，alembic `0031_drop_theme_suggestions`。
- `forward/`：`--hypothesis H1`（前瞻）。輸出「樣本不足（累積 0／250 日）」：第一個訊號日是 2026-11-16，副本還沒有新資料。
- `consistency/`：一致性檢查，`consistency.py` 以函式呼叫把起日改成 #689 的第一個訊號日 2024-11-01（命令列不能改）。這是 #689 挑出 H1 的同一段歷史，裡面的判定**不是 H1 的判定**，只用來比對。
- `consistency_vs_689.txt`：與 `pr-assets/689` 的 `run-20261114/formal/trust_rev-all` 比對，淨值（H1 與母體）、每日前 20 名、H1 每筆成交去掉 CR 後全部相同。
