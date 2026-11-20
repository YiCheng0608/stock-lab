# #892 第五輪 V1、V2 探索段

- 工具：`tools/research/round5_research.py` 第 1 版（#889，PR #890），程式在 commit `884fe5ee6f6bd0fe715c9bda5778abf24c71c83a`。
- image：`t892-backend:884fe5ee`，從同一個 commit 建。
- 容器：`research-892-exploration`，台北 2026-11-21 04:10 開跑，耗時 350 秒，工具記的峰值 1.87 GB，exit 0。
- 掛載照 docs/spec/evidence.md「第 2 步的工具」的 `R`＋`RERUN`：研究 volume `stock-lab-research` 掛在 `/research`，DB 以 `mode=ro`＋`query_only` 開，沒有掛 `/data`。
- 命令：`python -B tools/research/round5_research.py --db /research/stock.db --segment exploration --hypotheses V1,V2 --out /out/exploration`（不帶 V3）
- `explore.md` 第一行是 `explore.json` 的 sha256。
- `ledger-entries.json` 有 2 筆探索段紀錄，DB 旁的 `/research/explore-ledger.json` 也已寫入。
