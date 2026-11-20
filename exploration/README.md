# #884 第四輪 C1～C4 探索段

- 工具：`tools/research/round4_research.py` 第 1 版（#878，PR #883），程式在 commit `df5a3abcf49961858e77e4b16758bda8a9842f7e`。
- image：`t884-backend:df5a3abc`，從同一個 commit 建。
- 容器：`research-884-exploration`，台北 2026-11-21 01:51 開跑，耗時 229 秒，峰值 0.93 GB，exit 0。
- 掛載照 docs/spec/evidence.md「第 2 步的工具」的 `R`＋`RERUN`：研究 volume `stock-lab-research` 掛在 `/research`，DB 以 `mode=ro`＋`query_only` 開，沒有掛 `/data`。
- 命令：`python -B tools/research/round4_research.py --db /research/stock.db --segment exploration --hypotheses C1,C2,C3,C4 --out /out/exploration`
- `explore.md` 第一行是 `explore.json` 的 sha256。
- `ledger-entries.json` 有 4 筆探索段紀錄，DB 旁的 `/research/explore-ledger.json` 也已寫入。
