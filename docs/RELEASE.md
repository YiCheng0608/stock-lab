<!-- owns: 發佈流程、發佈 tag、部署、部署記錄、版本回退、V1 發佈隔離 -->
# 發佈與部署

排程在 compose 的 scheduler 容器裡跑 image 內的程式（[OPERATIONS §6.6](OPERATIONS.md#66-scheduler-容器的排程serve)），新版本只經 [`tools/ops/deploy.sh`](../tools/ops/deploy.sh) 進排程：build 該 tag 的 image、以 tag 名稱標記、`docker compose up -d`，每次部署都有 volume 裡的部署記錄與 #1 留言（#340，接手 #314 的固定 tag 流程）。部署屬使用者決策：由使用者或使用者明確授權的統籌執行（[無人值守運作](GITHUB_WORKFLOW.md#無人值守運作)的「需要使用者的事」）；腳本本身不檢查授權。

## 流程

V1 之後的發佈（使用者 2026-10-28 決定，取代 [V1 發佈隔離](#v1-發佈隔離g7-窗口專用)的 `release/*` 雙 PR）：

1. **合併**：改動照[任務流程](GITHUB_WORKFLOW.md#任務流程)以 PR 合併進 master，master 上該 merge commit 的 CI 綠。
2. **打 tag**：要發佈的版本範圍經使用者同意後，統籌在該 merge commit 打 annotated tag 並推上 GitHub。名稱 `v<主>.<次>.<修>`（tag 也是 image 的 tag，只能有英數字、`_`、`.`、`-`）；推上後不移動、不刪，要修正就打下一個。

   ```text
   git tag -a v1.1.0 <merge commit> -m "<版本摘要與 Issue>"
   git push origin v1.1.0
   ```

3. **部署**：排程閒置時（避開台北 18:30～21:30 的 daily），在 master 管理 checkout 執行 `bash tools/ops/deploy.sh v1.1.0 --operator "<誰，依據的 #1 留言>"`，見下節。
4. **讀回**：`deploy.sh` 輸出的 JSON 與 #1 留言；`docker compose -p stock-lab ps` 的 image 欄是 `stock-lab-backend:v1.1.0`／`stock-lab-web:v1.1.0`；下一次 daily 的 `schedule_runs.summary_json.runtime` 的 `image`／`head` 是該 tag 的 image 與 commit（[OPERATIONS §6.3](OPERATIONS.md#63-日誌與-run-記錄)）；看門狗的 `invariant_deploy_image` 不留言（[OPERATIONS §6.1](OPERATIONS.md#61-排程看門狗)）。

## 部署

`deploy.sh <tag> [--checkout DIR] [--project NAME] [--operator NAME] [--wait-timeout SEC] [--no-comment] [--python EXE]`。

- **發佈 checkout**（`--checkout`，預設 `STOCK_RELEASE_DIR`、再來是 `~/stock-lab-release`）是 compose 的 project 目錄：tag 在這裡 checkout，build context 與 `docker-compose.yml` 都是該 tag 的；`.env`（[OPERATIONS §6.7](OPERATIONS.md#67-容器內的-claude-與-gh-認證env)，不進 Git、git 忽略它，不算未 commit 的改動）也放在這裡。要從另一個 checkout 執行：checkout tag 會改寫發佈 checkout 的檔案，腳本在發佈 checkout 裡就拒絕。
- **compose project**（`--project`，預設 `STOCK_COMPOSE_PROJECT`、再來是 `stock-lab`）：image 是 `<project>-backend:<tag>`（api、scheduler）與 `<project>-web:<tag>`，資料在 volume `<project>_stock-data`。`COMPOSE_PROJECT_NAME` 不採用：任務 session 的它是 `task-<issue>`（[本機檢查](GITHUB_WORKFLOW.md#本機檢查)）。
- `--wait-timeout`：`compose up --wait` 等服務 healthy 的秒數，預設 300。`--no-comment` 不在 #1 留言，只用於臨時 checkout 與 project 的演練（[`tools/compose/deploy_smoke.sh`](../tools/compose/deploy_smoke.sh)，CI `compose` job）。

下列任一情況拒絕並 exit 1，發佈 checkout 的 HEAD、工作樹與 tag，以及 image、容器、volume 都不變（在 fetch 之後才發現的拒絕，會刪掉 fetch 新建的 tag ref；部署前就有的同名 tag 保留）：

| 檢查 | 拒絕條件 |
| --- | --- |
| 工作樹 | 有未 commit 的改動（含未追蹤的檔；git 忽略的檔不算），或有 `index.lock`／`MERGE_HEAD` |
| tag | `git ls-remote origin` 沒有這個 tag |
| CI | tag 所在 commit **自己的** CI（`gh run list --commit <sha> --workflow CI`）最新一次（run id 最大的，同時建立的 run 列出順序不定）不是 success：紅、執行中或沒有都拒絕。不要求是 master 的祖先（`release/v1` 的 commit 有自己的 CI） |
| 排程 | 執行中的 scheduler 容器裡，volume 的 `locks/` 的 daily、news、watchdog 鎖（[OPERATIONS §6.2](OPERATIONS.md#62-dailynews-工作的註冊與管理)，與 job 同一套檔案鎖）有任一被持有。三把鎖由 `docker exec` 在該容器內以 `worker.job lock --keep-stdin` 取得，持有到新容器起來、讀回完成（`deploy.sh` 關閉 stdin 或中途結束就釋放）；job 在這段時間起跑會記 `already_running`。舊 scheduler 被 `up` 換掉時鎖隨它釋放，新 scheduler 只在下一個觸發時間才跑 job。沒有執行中的 scheduler 時沒有排程 job 能跑，不取鎖（輸出 `"locks": "none"`） |
| 版本 | tag 早於 #340（tag 的 `docker-compose.yml` 沒有 `STOCK_RELEASE_TAG`）：那一版的 image 不帶 tag，部署後無法核對跑的版本。早於 #314 的 tag 也屬於這種 |

全部通過後依序：fetch 該 tag（本機已有同名但指向別處的 tag 時 fetch 失敗，拒絕）→ `git checkout <tag>`（detached HEAD）並讀回 HEAD → `docker compose build`（`STOCK_RELEASE_TAG=<tag>`、`STOCK_GIT_HEAD=<該 commit>`，image 內的 `STOCK_IMAGE_TAG`／`STOCK_GIT_HEAD` 就是這兩個）→ 在新 image 的臨時容器把部署記錄寫進 volume → `docker compose up -d --no-build --wait` → 讀回三個服務跑的都是該 tag 的 image、新 scheduler 自己的版本核對（`watchdog_helper.py deploy-image`）是 ok → 釋放鎖 → 在 #1 留言。

**部署記錄**在 volume 的 `/data/logs/deploy.json`（`<project>_stock-data`），每次部署覆寫，歷史在 #1 留言；寫的時候舊 scheduler 的看門狗鎖仍被持有，看門狗不會讀到一半：

```json
{"tag": "v1.1.0", "HEAD": "<完整 SHA>", "image": "stock-lab-backend:v1.1.0", "web_image": "stock-lab-web:v1.1.0", "previous_image": "<部署前 scheduler 的 image，沒有為 null>", "deployed_at": "2026-11-03T02:00:00Z", "operator": "<--operator>", "project": "stock-lab", "checkout": "<發佈 checkout>"}
```

看門狗在 scheduler 容器裡以它核對自己的 `STOCK_IMAGE_TAG`／`STOCK_GIT_HEAD`；不同（容器在 `deploy.sh` 之外重建，例如 `docker compose up -d --build` 會變成 `<project>-backend:latest`；或部署在寫記錄之後失敗）就在 #1 留言。

**#1 留言**的格式（測試 `test_the_comment_on_1_names_the_tag_head_images_and_record`）：

```text
部署：tag `v1.1.0` 的 image 已以 `docker compose up -d` 啟動

- HEAD：`<完整 SHA>`
- image：`stock-lab-backend:v1.1.0`（api、scheduler）、`stock-lab-web:v1.1.0`（web）；前一版 `stock-lab-backend:v1.0.1`
- compose project：`stock-lab`；發佈 checkout：`<發佈 checkout>`
- 操作者：<--operator>；時間：<deployed_at>（UTC）

（`tools/ops/deploy.sh` 自動留言；部署記錄在 volume 的 `/data/logs/deploy.json`，看門狗以它核對 scheduler 跑的 image。）
```

沒有執行中的 scheduler 時「前一版」寫「無（scheduler 沒有在執行）」。

| exit | 意義與處置 |
| --- | --- |
| 0 | 已部署並留言 |
| 1 | 拒絕，什麼都沒變；依訊息處理後再跑 |
| 3 | checkout 已開始後某一步失敗。寫記錄之前（checkout、build）：容器仍跑前一版，記錄也是前一版的；寫記錄之後（`up`、讀回）：看門狗會回報 scheduler 的 image 與記錄不符。修好原因後以同一個 tag 再跑 |
| 4 | 已部署、記錄已寫，只有 #1 留言失敗：手動補留言 |
| 2、64 | 環境（找不到 docker、Docker Desktop 沒開、拿不到鎖但不是被持有）或參數錯誤，沒有動作 |

## 版本回退

以 `deploy.sh <前一個 tag>` 部署回去，檢查與記錄相同；該 tag 的 image 還在時 build 走快取。資料庫 migration 不會跟著退：升級含 migration 的版本前照 [OPERATIONS §2.1](OPERATIONS.md#21-安全升級與復原順序) 先備份，回退時一併處理。

## V1 發佈隔離（G7 窗口專用）

只用於 V1 的 G7 窗口（使用者 2026-10-26 決定，#288）；窗口結束後不再使用，之後一律照上面的[流程](#流程)。窗口期間工作排程器從發佈 checkout 執行，發佈 checkout 跟著 `release/v1`，排程起跑前 `git pull --ff-only`（#314 前的 job）。

- **兩條 branch**：排程窗口期間發佈 checkout 跟發佈 branch `release/v1`（[OPERATIONS §6](OPERATIONS.md#6-排程)），master 照常合併 V1.1。`release/v1` 受 ruleset 保護（禁止刪除與強推、只經 PR 以 merge commit 合併、CI `required` 綠）。
- **V1 改動兩個 PR**：要進 V1 的改動（V1 milestone 的 Issue，含窗口中的修正）從同一條工作 branch 開兩個 PR，一個進 master、一個進 `release/v1`，兩個都要 CI 綠；工作 branch 只合併 `origin/release/v1`（不合併含 V1.1 的 master），進 master 的衝突在 master 那個 PR 解。`release/v1` 不合回 master，也不拿它當 PR 的 head（合併後會被自動刪 branch 設定刪掉）。每次進 `release/v1` 記在 G7 Issue。
- **真資料 verify** 在窗口的開頭與結尾各跑一次，兩次都用當時 `origin/release/v1` 的程式：worktree 從它建、不加 commit、不留未 commit 的改動（`page_checks.py --g7` 要求 HEAD 等於 `origin/release/v1`，不符合就拒跑）；人工檢查由另一個 session 依寫死的樣本判讀，整份證據再由另一個 session 獨立 review。
- **每日核對**記發佈 checkout 當時的 branch 與 HEAD（`git -C <發佈 checkout> rev-parse --abbrev-ref HEAD` 與 `--short HEAD`），證明窗口每天跑的是 `release/v1`。
- **窗口結束**（使用者確認 G7 後）：`git log origin/master..origin/release/v1 --no-merges` 必須為空（V1 改動都已在 master）；在排程閒置時把發佈 checkout 切回 master、依 master 的 lock 檔重裝 venv（下一次 daily 會升 V1.1 的 migration）；`release/v1` 最後一個 commit 打 `v1.0` tag。三項結果記在 G7 Issue。

窗口結束後到 Docker 切換（#342）之前，工作排程器仍從發佈 checkout 執行，發佈 checkout 不能拉到含 #333 的 commit（[OPERATIONS §6.6](OPERATIONS.md#66-scheduler-容器的排程serve) 的切換前提）。上面的 `deploy.sh` 部署的是 image，只在 scheduler 容器接手之後使用；切換步驟與切換時的第一次部署由 #342 處理。`v1.0` 早於 #340，`deploy.sh` 的版本檢查會拒絕它。
