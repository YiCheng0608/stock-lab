# #897 第五輪 V3 探索段

- 工具：`tools/research/round5_research.py` 第 1 版（#889，PR #890），程式在 commit `9ed0cf5ef119885350d53f05a20148add7006473`（master，含 #891、#899）。
- image：`t897-backend:9ed0cf5e`，從同一個 commit 建。
- 容器：`research-897-exploration`，台北 2026-11-21 07:50 開跑，耗時 548 秒，工具記的峰值 1.80 GB，exit 0；開跑前 `MemAvailable` 7.1 GB。
- 掛載照 docs/spec/evidence.md「第 2 步的工具」的 `R`＋`RERUN`：研究 volume `stock-lab-research` 掛在 `/research`（不加 `:ro`），`--network none --memory 4g --memory-swap 4g --oom-score-adj 1000`，DB 以 `mode=ro`＋`query_only` 開，沒有掛 `/data`。
- 命令：`python -B tools/research/round5_research.py --db /research/stock.db --segment exploration --hypotheses V3 --out /out/exploration`
- `explore.md` 第一行是 `explore.json` 的 sha256。
- `ledger-entries.json` 有 1 筆探索段紀錄，DB 旁的 `/research/explore-ledger.json` 也已寫入。
