<!-- owns: 發佈流程、發佈 tag、部署、部署記錄、版本回退、V1 發佈隔離 -->
# 發佈與部署

排程只執行發佈 checkout 目前 checkout 的版本（[OPERATIONS §6.2](OPERATIONS.md#62-dailynews-工作的註冊與管理)），起跑不 `git pull`；新版本只經 [`tools/ops/deploy.sh`](../tools/ops/deploy.sh) 進排程，每次部署都有本機記錄與 #1 留言（#314）。部署屬使用者決策：由使用者或使用者明確授權的統籌執行（[無人值守運作](GITHUB_WORKFLOW.md#無人值守運作)的「需要使用者的事」）；腳本本身不檢查授權。

## 流程

V1 之後的發佈（使用者 2026-10-28 決定，取代 [V1 發佈隔離](#v1-發佈隔離g7-窗口專用)的 `release/*` 雙 PR）：

1. **合併**：改動照[任務流程](GITHUB_WORKFLOW.md#任務流程)以 PR 合併進 master，master 上該 merge commit 的 CI 綠。
2. **打 tag**：要發佈的版本範圍經使用者同意後，統籌在該 merge commit 打 annotated tag 並推上 GitHub。名稱 `v<主>.<次>.<修>`；推上後不移動、不刪，要修正就打下一個。

   ```text
   git tag -a v1.1.0 <merge commit> -m "<版本摘要與 Issue>"
   git push origin v1.1.0
   ```

3. **部署**：排程閒置時（避開台北 18:30～21:30 的 daily），在 master 管理 checkout 執行 `bash tools/ops/deploy.sh v1.1.0 --operator "<誰，依據的 #1 留言>"`，見下節。
4. **讀回**：`deploy.sh` 輸出的 JSON 與 #1 留言；下一次 daily 的 `schedule_runs.summary_json` 的 `git_tag`／`HEAD` 等於該 tag（[OPERATIONS §6.3](OPERATIONS.md#63-日誌與-run-記錄)）；看門狗的 `invariant_deploy_head` 不留言（[OPERATIONS §6.1](OPERATIONS.md#61-排程看門狗)）。

## 部署

`deploy.sh <tag> [--checkout DIR] [--data-dir DIR] [--operator NAME] [--reinstall] [--no-comment] [--python EXE]`。發佈 checkout 預設 `STOCK_RELEASE_DIR`、再來是 `~/stock-lab-release`；資料目錄預設 `STOCK_DATA_DIR`、再來是 `~/stock-lab-data`。要從另一個 checkout 執行：checkout tag 會改寫發佈 checkout 的檔案，腳本在發佈 checkout 裡就拒絕。

下列任一情況拒絕並 exit 1，發佈 checkout 的 HEAD、工作樹與 tag 都不變：

| 檢查 | 拒絕條件 |
| --- | --- |
| 工作樹 | 有未 commit 的改動（含未追蹤的檔），或有 `index.lock`／`MERGE_HEAD` |
| tag | `git ls-remote origin` 沒有這個 tag |
| CI | tag 所在 commit **自己的** CI（`gh run list --commit <sha> --workflow CI`）最新一次不是 success：紅、執行中或沒有都拒絕。不要求是 master 的祖先（`release/v1` 的 commit 有自己的 CI） |
| 排程 | 資料目錄 `locks/` 的 daily、news、watchdog 鎖（[OPERATIONS §6.2](OPERATIONS.md#62-dailynews-工作的註冊與管理)，與 job 同一套檔案鎖）有任一被持有。三把鎖在之後的 checkout、venv 重裝與寫記錄期間一直持有，job 在這段時間起跑會記 `already_running` |
| 版本 | tag 早於 #314（tag 裡沒有 `tools/ops/deploy.sh`）：那一版的 job 起跑前會 `git pull`，在 detached HEAD 上每次都記 `git_pull_failed`。`v1.0`（`release/v1` 沒有 #314）屬於這種，第一次部署要用含 #314 的 tag |

全部通過後依序：fetch 該 tag（本機已有同名但指向別處的 tag 時 fetch 失敗，拒絕）→ `git checkout <tag>`（detached HEAD）→ `backend/requirements.txt` 或 `backend/validation-requirements.lock.txt` 與前一版不同（或加 `--reinstall`）時以發佈 checkout 的 `.venv` 執行 `pip install -r backend/requirements.txt -c backend/validation-requirements.lock.txt` → 讀回 HEAD → 寫部署記錄 → 釋放鎖 → 在 #1 留言 tag 與 HEAD（`--no-comment` 不留，只用於臨時 checkout 的演練）。

**部署記錄** `<資料目錄>/logs/deploy.json`，每次部署覆寫，歷史在 #1 留言：

```json
{"tag": "v1.1.0", "HEAD": "<完整 SHA>", "previous_HEAD": "<部署前的 SHA>", "deployed_at": "2026-11-03T02:00:00Z", "operator": "<--operator>", "checkout": "<發佈 checkout>", "venv_reinstalled": false}
```

看門狗以它核對發佈 checkout 的 HEAD；兩者不同（有人手動 checkout、或部署中途失敗）就在 #1 留言。

| exit | 意義與處置 |
| --- | --- |
| 0 | 已部署並留言 |
| 1 | 拒絕，發佈 checkout 不變；依訊息處理後再跑 |
| 3 | checkout 已開始後某一步失敗（checkout、讀回、venv 重裝、寫記錄），不寫部署記錄，看門狗會回報 HEAD 與記錄不符；修好原因後以同一個 tag 再跑（venv 重裝失敗時加 `--reinstall`） |
| 4 | 已部署、記錄已寫，只有 #1 留言失敗：手動補留言 |
| 2、64 | 環境或參數錯誤，沒有動作 |

## 版本回退

以 `deploy.sh <前一個 tag>` 部署回去，檢查與記錄相同。資料庫 migration 不會跟著退：升級含 migration 的版本前照 [OPERATIONS §2.1](OPERATIONS.md#21-安全升級與復原順序) 先備份，回退時一併處理。

## V1 發佈隔離（G7 窗口專用）

V1 G7 窗口專用（使用者 2026-10-26 決定，#288）；窗口結束後不再使用，之後一律照上面的[流程](#流程)。窗口期間發佈 checkout 跟著 `release/v1`，排程起跑前 `git pull --ff-only`（#314 前的 job）。

- **兩條 branch**：排程窗口期間發佈 checkout 跟發佈 branch `release/v1`（[OPERATIONS §6](OPERATIONS.md#6-排程)），master 照常合併 V1.1。`release/v1` 受 ruleset 保護（禁止刪除與強推、只經 PR 以 merge commit 合併、CI `required` 綠）。
- **V1 改動兩個 PR**：要進 V1 的改動（V1 milestone 的 Issue，含窗口中的修正）從同一條工作 branch 開兩個 PR，一個進 master、一個進 `release/v1`，兩個都要 CI 綠；工作 branch 只合併 `origin/release/v1`（不合併含 V1.1 的 master），進 master 的衝突在 master 那個 PR 解。`release/v1` 不合回 master，也不拿它當 PR 的 head（合併後會被自動刪 branch 設定刪掉）。每次進 `release/v1` 記在 G7 Issue。
- **真資料 verify** 在窗口的開頭與結尾各跑一次，兩次都用當時 `origin/release/v1` 的程式：worktree 從它建、不加 commit、不留未 commit 的改動（`page_checks.py --g7` 要求 HEAD 等於 `origin/release/v1`，不符合就拒跑）；人工檢查由另一個 session 依寫死的樣本判讀，整份證據再由另一個 session 獨立 review。
- **每日核對**記發佈 checkout 當時的 branch 與 HEAD（`git -C <發佈 checkout> rev-parse --abbrev-ref HEAD` 與 `--short HEAD`），證明窗口每天跑的是 `release/v1`。
- **窗口結束**（使用者確認 G7 後）：`git log origin/master..origin/release/v1 --no-merges` 必須為空（V1 改動都已在 master）；在排程閒置時把發佈 checkout 切回 master、依 master 的 lock 檔重裝 venv（下一次 daily 會升 V1.1 的 migration）；`release/v1` 最後一個 commit 打 `v1.0` tag。三項結果記在 G7 Issue。

窗口結束後到第一次部署之間：發佈 checkout 在 master 上，#314 前的 job 仍在起跑前 pull；#314 合併進 master 後，下一次 pull 就帶進不 pull 的 job，發佈 checkout 從此停在那個 commit，直到第一次以 `deploy.sh` 部署含 #314 的 tag。這段期間還沒有部署記錄，看門狗的 `invariant_deploy_head` 印 `skip`、不留言。
