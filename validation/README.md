# #928 第八輪 Z2 驗證段

- 工具：`tools/research/round8_research.py` 第 1 版（#918，PR #921）；image `t928-backend:172e21ee`，從 commit `172e21ee2ad760b15bd801412bff1160a76cfe85`（master，PR #924 的 merge commit）建，`definitions_sha256` `cd00cd2d201893370ec706168af5a30cb8e1e684c47ba30fc91356447876d757`。
- 紀錄裡的 `tool_commit` 是 `91f97245deec713c78ac4178aadc01217a405664`：工具在容器裡讀 worktree 的 HEAD，開跑時 HEAD 已是本單 branch 的 commit（只在 172e21ee 之上改了 `tools/research/explore_ledger.json` 與 `docs/spec/evidence.md`，工具程式與 image 相同）。這個 commit 照原樣放進本單的 PR。`tool_commit` 不算進報告雜湊。
- 依統籌決定 https://github.com/YiCheng0608/stock-lab/issues/928#issuecomment-7057222845 跑一次。
- 容器：`research-928-validation`，台北 2026-11-21 12:23 開跑、12:26 結束，耗時 170 秒（工具記），峰值記憶體 1.12 GB，exit 0；開跑前容器內 `MemAvailable` 約 6.6 GiB，`docker ps` 沒有其他 `research-*` 容器，沒有回補在跑。
- 掛載照 docs/spec/evidence.md「第 2 步的工具」的 `R`（不加 `RERUN`、不加 `:ro`）。
- 命令：`python -B tools/research/round8_research.py --db /research/stock.db --segment validation --exploration-report /out/exploration/explore.json --exploration-sha256 f2a8c8df49f560f6352afb3114ee013b692e65e01ca9e9b0f7c3982822a93622 --exploration-url https://github.com/YiCheng0608/stock-lab/blob/pr-assets/928/exploration/explore.json --out /out/validation`
- 判定「驗證段反轉」，沒有跑已用段。
- `explore.md` 第一行是 `explore.json` 的 sha256。`ledger-entries.json` 有 1 筆驗證段紀錄，DB 旁的 `/research/explore-ledger.json` 也已寫入。
- 工具留下的空 `raw/` 目錄推之前刪掉。
