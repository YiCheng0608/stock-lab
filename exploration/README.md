# #928 第八輪 Z1～Z4 探索段

- 工具：`tools/research/round8_research.py` 第 1 版（#918，PR #921），程式在 commit `172e21ee2ad760b15bd801412bff1160a76cfe85`（master，PR #924 的 merge commit，含 PR #921 的 `83c9efe9`）；`definitions_sha256` `cd00cd2d201893370ec706168af5a30cb8e1e684c47ba30fc91356447876d757`。
- image：`t928-backend:172e21ee`，從同一個 commit 建。
- 容器：`research-928-explore`，台北 2026-11-21 12:08 開跑、12:19 結束，耗時 684 秒（工具記），峰值記憶體 2.00 GB，exit 0；開跑前容器內 `MemAvailable` 約 6.7 GiB，`docker ps` 沒有其他 `research-*` 容器。
- 掛載照 docs/spec/evidence.md「第 2 步的工具」的 `R`＋`RERUN`：研究 volume `stock-lab-research` 掛在 `/research`（不加 `:ro`），`--network none --memory 4g --memory-swap 4g --oom-score-adj 1000`，DB 以 `mode=ro`＋`query_only` 開，沒有掛 `/data`。
- 命令：`python -B tools/research/round8_research.py --db /research/stock.db --segment exploration --hypotheses Z1,Z2,Z3,Z4 --out /out/exploration`
- `explore.md` 第一行是 `explore.json` 的 sha256。
- `ledger-entries.json` 有 4 筆探索段紀錄，DB 旁的 `/research/explore-ledger.json` 也已寫入（共 36 筆）。
- 工具留下的空 `raw/` 目錄（沒有檔案）推之前刪掉，不影響報告與雜湊。
