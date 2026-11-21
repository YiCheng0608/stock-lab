# #916 第七輪 Y1～Y4 探索段

- 工具：`tools/research/round7_research.py` 第 1 版（#912，PR #913），程式在 commit `fbe38b5888df00fb414bb1051befe5ef7bfb817a`（master，PR #913 的 merge commit）；`definitions_sha256` `180c21a4307b5cfd16db0b246478f5da3406a9779b0956dfc13cb32dc0cd47d7`。
- image：`t916-backend:fbe38b58`，從同一個 commit 建。
- 容器：`research-916-explore`，台北 2026-11-21 10:01 開跑、10:11 結束，耗時 591 秒（工具記），峰值記憶體 1.93 GB，exit 0；開跑前容器內 `MemAvailable` 約 6.7 GiB，`docker ps` 沒有其他 `research-*` 容器。
- 掛載照 docs/spec/evidence.md「第 2 步的工具」的 `R`＋`RERUN`：研究 volume `stock-lab-research` 掛在 `/research`（不加 `:ro`），`--network none --memory 4g --memory-swap 4g --oom-score-adj 1000`，DB 以 `mode=ro`＋`query_only` 開，沒有掛 `/data`。
- 命令：`python -B tools/research/round7_research.py --db /research/stock.db --segment exploration --hypotheses Y1,Y2,Y3,Y4 --out /out/exploration`
- `explore.md` 第一行是 `explore.json` 的 sha256。
- `ledger-entries.json` 有 4 筆探索段紀錄，DB 旁的 `/research/explore-ledger.json` 也已寫入。
