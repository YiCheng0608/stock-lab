# AC-5 重跑的主機量測（#1069，台北 2026-11-28）

- 10:11 容器內 MemAvailable 4817024 kB；df /System/Volumes/Data 可用 8.4Gi
- 10:11:45 取副本第一次：copy_db 拒絕（immutable 讀取期間正式 DB 被開啟），377.8 s，已自動移除
- 10:18 curl /api/candidate-pool 200 後重取：ro、quick_check ok、4575412224 bytes、313.9 s、latest 2026-11-27、alembic 0041_valuation_shares（copy.json）
- 10:23 跑 review 前 MemAvailable 4802128 kB
- 10:23:40～10:29:22 monthly_review --month 2026-11：13/13 成功、338.0 s；review.json peak_memory_gb 0.62；容器 cgroup memory.peak 1611108352 bytes（--memory 2g，含 page cache）
- 10:29 docker volume rm task-1069_db 後 df 可用 2.6Gi（取副本前 8.4Gi；docker system df 已無 task-1069_db，其他寫入者：research-1083-statements2 等）
