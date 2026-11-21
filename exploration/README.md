# #906 第六輪 W1～W4 探索段

- 工具：`tools/research/round6_research.py` 第 1 版（#903，PR #905），程式在 commit `ac9ee9fc0214aedde574c583db702800af0ce9cd`（master，PR #905 的 merge commit）；`definitions_sha256` `b8e1eb89a20b9ea97db4d6ba38a1461d5ff5bf05b26eb9619c353db7020ac51e`。
- image：`t906-backend:ac9ee9fc`，從同一個 commit 建。
- 容器：`research-906-explore`，台北 2026-11-21 09:12 開跑，耗時 437 秒（工具記），峰值記憶體 1.83 GB，exit 0；開跑前容器內 `MemAvailable` 約 6.7 GiB，`docker ps` 沒有其他 `research-*` 容器。
- 掛載照 docs/spec/evidence.md「第 2 步的工具」的 `R`＋`RERUN`：研究 volume `stock-lab-research` 掛在 `/research`（不加 `:ro`），`--network none --memory 4g --memory-swap 4g --oom-score-adj 1000`，DB 以 `mode=ro`＋`query_only` 開，沒有掛 `/data`。
- 命令：`python -B tools/research/round6_research.py --db /research/stock.db --segment exploration --hypotheses W1,W2,W3,W4 --out /out/exploration`
- `explore.md` 第一行是 `explore.json` 的 sha256。
- `ledger-entries.json` 有 4 筆探索段紀錄，DB 旁的 `/research/explore-ledger.json` 也已寫入。
