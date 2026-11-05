<!-- owns: 發佈流程、發佈 tag、部署、部署記錄、版本回退、V1 發佈隔離 -->
# 發佈與部署

排程在 compose 的 scheduler 容器裡跑 image 內的程式（[scheduler 容器的排程（serve）](ops/SCHEDULING.md#scheduler-容器的排程serve)），新版本只經 [`tools/ops/deploy.sh`](../tools/ops/deploy.sh) 進排程：build 該 tag 的 image、以 tag 名稱標記、`docker compose up -d`，每次部署都有 volume 裡的部署記錄與 #1 留言（#340，接手 #314 的固定 tag 流程）。部署屬使用者決策：由使用者或使用者明確授權的統籌執行（[無人值守運作](COORDINATOR.md#無人值守運作)的「需要使用者的事」）；腳本本身不檢查授權。

## 流程

V1 之後的發佈（使用者 2026-10-28 決定，取代 [V1 發佈隔離](#v1-發佈隔離g7-窗口專用)的 `release/*` 雙 PR）：

1. **合併**：改動照[任務流程](WORKFLOW.md#任務流程)以 PR 合併進 master，master 上該 merge commit 的 CI 綠。
2. **打 tag**：要發佈的版本範圍經使用者同意後，統籌在該 merge commit 打 annotated tag 並推上 GitHub。名稱 `v<主>.<次>.<修>`（tag 也是 image 的 tag，只能有英數字、`_`、`.`、`-`）；推上後不移動、不刪，要修正就打下一個。

   ```text
   git tag -a v1.1.0 <merge commit> -m "<版本摘要與 Issue>"
   git push origin v1.1.0
   ```

3. **部署**：排程閒置時（避開台北 21:30～23:30 的 daily：21:30 與 23:00 兩次，#466），在 master 管理 checkout 執行 `bash tools/ops/deploy.sh v1.1.0 --operator "<誰，依據的 #1 留言>"`，見下節。tag 比正式 DB 多了 migration 時，先照[含 migration 的版本](#含-migration-的版本)用新 tag 的程式升級 DB，再跑 `deploy.sh`；沒升級就跑，`deploy.sh` 在 build 之後、換容器之前拒絕（下節的「DB revision」）。
4. **讀回**：`deploy.sh` 輸出的 JSON 與 #1 留言；`docker compose -p stock-lab ps` 的 image 欄是 `stock-lab-backend:v1.1.0`／`stock-lab-web:v1.1.0`；下一次 daily 的 `schedule_runs.summary_json.runtime` 的 `image`／`head` 是該 tag 的 image 與 commit（[日誌與 run 記錄](ops/SCHEDULING.md#日誌與-run-記錄)）；看門狗的 `invariant_deploy_image` 不留言（[排程看門狗](ops/WATCHDOG.md)）。

## 部署

`deploy.sh <tag> [--checkout DIR] [--project NAME] [--operator NAME] [--wait-timeout SEC] [--web-port N] [--api-port N] [--env-file PATH] [--no-comment] [--python EXE]`。

- **發佈 checkout**（`--checkout`，預設 `STOCK_RELEASE_DIR`、再來是 `~/stock-lab-release`）是 compose 的 project 目錄：tag 在這裡 checkout，build context 與 `docker-compose.yml` 都是該 tag 的；`.env`（[容器內的 claude 與 gh 認證（.env）](ops/SETUP.md#容器內的-claude-與-gh-認證env)，不進 Git、git 忽略它，不算未 commit 的改動）也放在這裡。要從另一個 checkout 執行：checkout tag 會改寫發佈 checkout 的檔案，腳本在發佈 checkout 裡就拒絕。
- **compose project**（`--project`，預設 `STOCK_COMPOSE_PROJECT`、再來是 `stock-lab`）：image 是 `<project>-backend:<tag>`（api、scheduler）與 `<project>-web:<tag>`，資料在 volume `<project>_stock-data`。`COMPOSE_PROJECT_NAME` 不採用：任務 session 的它是 `task-<issue>`（[本機檢查](WORKFLOW.md#本機檢查)）。
- `--wait-timeout`：`compose up --wait` 等服務 healthy 的秒數，預設 300。`--no-comment` 不在 #1 留言，只用於臨時 checkout 與 project 的演練（[`tools/compose/deploy_smoke.sh`](../tools/compose/deploy_smoke.sh)，CI `compose` job）。
- `WEB_PORT`、`API_PORT`、`STOCK_ENV_FILE`（[Docker compose](ops/SETUP.md#docker-compose)）：呼叫端 shell 裡的這三個變數一律丟掉，避免剛跑過 smoke 的 shell 把正式 project 換到別的埠或 env file。compose 改從發佈 checkout 的 `.env`、再來是 compose 檔的預設取得；要指定時用 `--web-port`、`--api-port`、`--env-file`（演練用）。

下列任一情況拒絕並 exit 1，發佈 checkout 的 HEAD、工作樹與 tag，以及 image、容器、volume 都不變（在 fetch 之後才發現的拒絕，會刪掉 fetch 新建的 tag ref；部署前就有的同名 tag 保留；DB revision 一項在 build 之後，只多出新 build 的 image）：

| 檢查 | 拒絕條件 |
| --- | --- |
| 工作樹 | 有未 commit 的改動（含未追蹤的檔；git 忽略的檔不算），或有 `index.lock`／`MERGE_HEAD` |
| tag | `git ls-remote origin` 沒有這個 tag |
| CI | tag 所在 commit **自己的** CI（`gh run list --commit <sha> --workflow CI`）最新一次（run id 最大的，同時建立的 run 列出順序不定）不是 success：紅、執行中或沒有都拒絕。不要求是 master 的祖先（`release/v1` 的 commit 有自己的 CI） |
| 排程 | volume 的 `locks/` 的 daily、news、watchdog 鎖（[daily／news 工作的註冊與管理](ops/platform/windows.md#dailynews-工作的註冊與管理)，與 job 同一套檔案鎖）有任一被持有。三把鎖由 `docker exec` 在該 project 一個執行中、掛著 volume 的容器內以 `worker.job lock --keep-stdin` 取得：scheduler 優先，沒有時用 api 或 `compose run` 的臨時容器（手動跑的 job 也在這裡被擋下）。鎖持有到新容器起來、讀回完成（`deploy.sh` 關閉 stdin 或中途結束就釋放）；job 在這段時間起跑會記 `already_running`。舊容器被 `up` 換掉時鎖隨它釋放，新 scheduler 只在下一個觸發時間才跑 job。api、scheduler 都沒在執行時沒有 job 能持有鎖，不取鎖（輸出 `"locks": "none"`） |
| 版本 | tag 早於 #340（tag 的 `docker-compose.yml` 沒有 `STOCK_RELEASE_TAG`）：那一版的 image 不帶 tag，部署後無法核對跑的版本。早於 #314 的 tag 也屬於這種 |
| DB revision（#456） | build 之後、換任何容器之前，新 backend image 的臨時容器（`docker run --rm --network none`，volume 以 `:ro` 唯讀掛載，[`db_revision.py`](../tools/ops/db_revision.py) 經 stdin 傳入）以 `mode=ro` 讀 volume 裡 DB 的 `alembic_version`，與該 image 的 alembic head（`app/migration_revisions.py` 最後一個）比對，不相同就拒絕。**落後**（DB 的 revision 在 tag 的 chain 裡但較舊）：訊息寫出兩個 revision，stderr 印出開維護模式（scheduler 是 #468 以前的 image 時改為停 scheduler）、備份、換 tag 與 `init-db` 的命令，照[含 migration 的版本](#含-migration-的版本)做完再以同一個 tag 重跑。**超前**（DB 的 revision 不在 tag 的 chain 裡，例如部署回舊 tag）：照[版本回退](#版本回退)。沒有 `<project>_stock-data` volume（先查，`docker run -v` 會建出空的）、volume 裡沒有 `stock.db`、`alembic_version` 不是恰好一列也拒絕。輸出的 JSON 多 `db_revision`、`head` 兩欄。腳本不跑 `init-db`、不寫 DB。這一項拒絕時剛 build 的 image 留著（之後的 build 走快取），發佈 checkout 退回部署前的 HEAD（原本在 branch 上就回到該 branch），fetch 新建的 tag ref 刪掉 |

全部通過後依序：fetch 該 tag（本機已有同名但指向別處的 tag 時 fetch 失敗，拒絕）→ `git checkout <tag>`（detached HEAD）並讀回 HEAD → `docker compose build`（`STOCK_RELEASE_TAG=<tag>`、`STOCK_GIT_HEAD=<該 commit>`，image 內的 `STOCK_IMAGE_TAG`／`STOCK_GIT_HEAD` 就是這兩個）→ 以新 image 唯讀比對 DB revision（上表最後一列）→ 在新 image 的臨時容器把部署記錄寫進 volume → `docker compose up -d --no-build --wait` → 讀回三個服務跑的都是該 tag 的 image、新 scheduler 自己的版本核對（`watchdog_helper.py deploy-image`）是 ok → 在新 scheduler 跑 `maintenance off --only-manual`，關掉手動開的維護模式，結果補寫進部署記錄的 `maintenance`（#468）→ 釋放鎖 → 在 #1 留言。

**部署記錄**在 volume 的 `/data/logs/deploy.json`（`<project>_stock-data`），每次部署覆寫，歷史在 #1 留言；寫的時候舊 scheduler 的看門狗鎖仍被持有，看門狗不會讀到一半：

```json
{"tag": "v1.1.0", "HEAD": "<完整 SHA>", "image": "stock-lab-backend:v1.1.0", "web_image": "stock-lab-web:v1.1.0", "previous_image": "<部署前 scheduler 的 image，沒有為 null>", "deployed_at": "2026-11-03T02:00:00Z", "operator": "<--operator>", "project": "stock-lab", "checkout": "<發佈 checkout>", "maintenance": "none"}
```

`maintenance`（#468）是新容器核對通過後，`deploy.sh` 對手動維護模式做了什麼：`turned_off`（[含 migration 的版本](#含-migration-的版本)第 1 步手動開的，已關掉）、`none`（沒開）、`kept_command_held`（回補或回測持有，不動）、`failed`（關不掉；部署照樣成立，看門狗 12 小時後提醒）。這一欄在 `compose up` 之後才補寫，所以 `up` 或讀回失敗的部署記錄沒有它。

看門狗在 scheduler 容器裡以它核對自己的 `STOCK_IMAGE_TAG`／`STOCK_GIT_HEAD`；不同（容器在 `deploy.sh` 之外重建，例如 `docker compose up -d --build` 會變成 `<project>-backend:latest`；或部署在寫記錄之後失敗）就在 #1 留言。

**#1 留言**的格式（測試 `test_the_comment_on_1_names_the_tag_head_images_and_record`）：

```text
部署：tag `v1.1.0` 的 image 已以 `docker compose up -d` 啟動

- HEAD：`<完整 SHA>`
- image：`stock-lab-backend:v1.1.0`（api、scheduler）、`stock-lab-web:v1.1.0`（web）；前一版 `stock-lab-backend:v1.0.1`
- compose project：`stock-lab`；發佈 checkout：`<發佈 checkout>`
- 操作者：<--operator>；時間：<deployed_at>（UTC）
- 維護模式：`<maintenance>`（turned_off＝手動開的已在部署後關掉；none＝沒開；kept_command_held＝回補或回測持有，不動；failed＝關不掉，看門狗 12 小時後提醒）

（`tools/ops/deploy.sh` 自動留言；部署記錄在 volume 的 `/data/logs/deploy.json`，看門狗以它核對 scheduler 跑的 image。）
```

沒有執行中的 scheduler 時「前一版」寫「無（scheduler 沒有在執行）」。

| exit | 意義與處置 |
| --- | --- |
| 0 | 已部署並留言 |
| 1 | 拒絕，容器、volume 與發佈 checkout 都沒變（DB revision 拒絕時多了新 build 的 image）；依訊息處理後再跑 |
| 3 | checkout 已開始後某一步失敗。寫記錄之前（checkout、build）：容器仍跑前一版，記錄也是前一版的；寫記錄之後（`up`、讀回）：看門狗會回報 scheduler 的 image 與記錄不符。修好原因後以同一個 tag 再跑 |
| 4 | 已部署、記錄已寫，只有 #1 留言失敗：手動補留言 |
| 2、64 | 環境或參數錯誤，沒有動作：找不到 docker、Docker Desktop 沒開；拿鎖的容器 120 秒內沒有回應；拿鎖的容器是 #340 之前的 image，它的 `worker.job` 不認得 `--keep-stdin`：先 `docker compose -p <project> stop` 停掉舊容器再部署（#342 切換時若已有舊的 scheduler 或 api 在跑也一樣） |

## 含 migration 的版本

tag 的 Alembic head（`backend/app/migration_revisions.py` 的最後一個）比正式 DB 的 `alembic_version` 新時，要先用**新 tag 的程式**升級 DB，再跑 `deploy.sh`（例如 0024，[#462](https://github.com/YiCheng0608/stock-lab/issues/462)）；順序是 SETUP 的[安全升級與復原順序](ops/SETUP.md#安全升級與復原順序)（備份、`init-db`、驗證），下面是它在正式 compose project 的寫法。原因有兩個：

- api 的 readiness 只接受 current head，DB 落後時新 api 拒絕啟動。`v1.2.0` 第一次部署就是這樣失敗的：`up` 換掉 scheduler 與 web 之後 api 才起不來。現在 `deploy.sh` 在 build 之後、換任何容器之前比對 DB revision 與 tag 的 head，落後就拒絕（[#456](https://github.com/YiCheng0608/stock-lab/issues/456)，上節表格的「DB revision」），所有容器仍跑前一版。
- 正式環境跑著的舊 image 不認得新 revision，用它跑 `init-db` 只會停在舊 head。

`deploy.sh` 只擋下、不升級：備份與 `init-db` 仍是人工步驟，在 master 管理 checkout 的 Git Bash 依序執行（`deploy.sh` 拒絕時在 stderr 印出第 1～4 步填好 tag、project 與發佈 checkout 的命令）。時段選排程閒置時：避開台北 21:30～23:30 的 daily（#466），也避開 news 每 2 小時的偶數整點，例如奇數點。

```bash
# 換值：TAG＝要部署的 tag；P＝正式 compose project；R＝發佈 checkout；B＝備份目錄（docs/ops/LOCAL.md）
TAG=v1.3.0 P=stock-lab
R="$(cd ~/stock-lab-release && pwd -W)"
B="C:/Users/YiCheng/stock-lab-backups/pre-$TAG-$(date +%Y%m%d)"
TOOLS="$(pwd -W)/tools/ops"; mkdir -p "$B"
OLD="$(docker inspect -f '{{.Config.Image}}' "$P-api-1")"   # 目前跑的 image，例如 stock-lab-backend:v1.2.0
unset WEB_PORT API_PORT STOCK_ENV_FILE   # 同 deploy.sh：不沿用 smoke 留下的設定
export MSYS_NO_PATHCONV=1   # 否則 Git Bash 會改寫 -v 的容器路徑

# 1. 維護模式：daily 與 news 停下，看門狗與 monitor 照常；api 照常服務舊版頁面。
#    status 的 running_jobs 要是 []，不是就等那個 job 跑完再查。scheduler 是 #468 以前的
#    image（v1.2.3 以前）時沒有這個命令（invalid choice），改用 docker compose -p "$P" stop scheduler
docker compose -p "$P" exec scheduler python -m worker.cli maintenance on --reason "$TAG"
docker compose -p "$P" exec scheduler python -m worker.cli maintenance status

# 2. 備份（唯讀連線，含 WAL）。輸出的 alembic_version 是 DB 目前的 revision，quick_check 是 ok。
#    api 開著 DB 時 source_open 應是 ro；沒有連線開著、volume 裡沒有 -wal／-shm 時，copy_db.py
#    以 immutable 開主檔，source_open 是 immutable（#486，docs/ops/LOCAL.md「取正式 DB 的唯讀
#    副本」）；exit 1 說有 -wal 或 -journal 時，先讓 api 開一次 DB（打任一個 API）再重跑
docker run --rm --network none -v "${P}_stock-data":/data:ro -v "$B":/out \
  -v "$TOOLS/copy_db.py":/t/copy_db.py:ro "$OLD" python /t/copy_db.py --src /data/stock.db --dest /out

# 3. 發佈 checkout 換成新 tag，以新 tag 的程式 build backend image
git -C "$R" fetch --quiet --no-tags origin "refs/tags/$TAG:refs/tags/$TAG"
git -C "$R" -c advice.detachedHead=false checkout --quiet "refs/tags/$TAG"
git -C "$R" show "$TAG:backend/app/migration_revisions.py" | grep -o '"0[0-9]*_[a-z_]*"' | tail -1   # tag 的 head
(cd "$R" && STOCK_RELEASE_TAG="$TAG" STOCK_GIT_HEAD="$(git rev-parse HEAD)" docker compose -p "$P" build api)

# 4. 以新 image 升級正式 DB（臨時容器；正在跑的舊 api 不受影響）
(cd "$R" && STOCK_RELEASE_TAG="$TAG" docker compose -p "$P" run --rm --no-deps api python -m worker.cli init-db)

# 5. 驗證：revision 是 tag 的 head，integrity 是 ok，foreign key 沒有違反
(cd "$R" && STOCK_RELEASE_TAG="$TAG" docker compose -p "$P" run --rm --no-deps api python -c "import sqlite3; c = sqlite3.connect('/data/stock.db'); print(c.execute('select version_num from alembic_version').fetchall(), c.execute('pragma integrity_check').fetchall(), c.execute('pragma foreign_key_check').fetchall())")

# 6. 部署（見上節；build 走快取，up 會連同 scheduler 一起換成新 tag 並啟動）。換完容器、核對都通過後，
#    deploy.sh 自己關掉第 1 步手動開的維護模式（部署記錄的 maintenance 是 turned_off；21:30 後部署的，
#    serve 解除時立即補跑當日 daily）。部署失敗時維護模式留著，看門狗 12 小時後提醒
bash tools/ops/deploy.sh "$TAG" --operator "<誰，依據的 #1 留言>"
```

- **第 1 步用維護模式就夠**（#468）：維護模式中 serve 啟動的程序都不寫 `stock.db`。daily、news 只記日誌、不啟動 worker（連 skipped run 列也不寫）；看門狗以 `mode=ro`、`query_only` 讀 DB，DB 是 WAL，讀取不擋 `init-db` 的寫入；monitor 不開 DB（[維護模式](ops/SCHEDULING.md#維護模式)的「serve 不寫 DB 的範圍」）。開啟前就在跑的 job 由 `status` 的 `running_jobs` 看出來，所以要等它是 `[]`。手動開的維護模式沒有心跳、不會逾時解除，由第 6 步的 `deploy.sh` 關掉；作業持有的（例如同時在跑的回補）`deploy.sh` 不動，記 `kept_command_held`。好處是看門狗與 monitor 不停，部署期間的留言與 CI 事件照常喚醒統籌。`v1.2.1` 部署前是在 scheduler 停止的狀態下跑 `init-db`；正式 scheduler 還是 #468 以前的 image 時照那樣做。
- **時間**：`init-db` 會先做遷移前的 schema 檢查。0023 → 0024 在正式副本上約 4 分鐘（238.5 s，建 index 本身不到 1 秒）；0025 → 0026 約 1 分 40 秒（98.9 s，含回補 15,614 筆 `events.updated_at`，[#476](https://github.com/YiCheng0608/stock-lab/issues/476)）；0026 → 0027 約 2 分 16 秒（136 s，2026-11-05 副本 3.0 GB，只建空表 `emerging_issuers`，[#512](https://github.com/YiCheng0608/stock-lab/issues/512)；名冊要等升級後第一次 collect 才有資料，在那之前興櫃候選照「查無」隱藏）。這段時間 api 照常服務。
- **部署後的補算**（#476 起）：第 6 步完成後，在新的 api 容器跑以下兩個命令。兩者都冪等，不跑也不會錯，只是第一個開頁的人要等即時計算：
  - `docker compose -p "$P" exec api python -m worker.cli news-project`：tag 改了投影規則（`NEWS_PROJECTION_VERSION`），或第一次部署含 #476 的版本時跑。
  - `docker compose -p "$P" exec api python -m worker.cli action-tiers`：預算最新官方日的 action tier。之後由 daily 的 action_tiers 步驟寫入（[action tier 預算與新聞投影](ops/SCHEDULING.md#action-tier-預算與新聞投影)）。
- **`deploy.sh` 不會因為前面幾步拒絕**：發佈 checkout 停在同一個 tag，工作樹乾淨；本機已有的同名 tag 指向同一個 commit，fetch 照常通過；維護模式下 scheduler 照常在跑，`deploy.sh` 在它裡面取鎖（第 1 步停了 scheduler 時改在 api 容器）；第 4 步之後 DB 已在 tag 的 head，revision 比對通過。新 scheduler 起來時標記檔還在，所以它不在啟動時補跑 daily；`deploy.sh` 關掉維護模式後，serve 在一分鐘內偵測到解除，需要時補跑。
- **第 6 步完成前不要關維護模式，也不要再啟動舊的 scheduler**：舊 scheduler 的 daily 起跑時會用自己的程式跑 `init_db`。舊 image 不認得新 revision，會失敗。第 6 步被拒絕或失敗時，修好原因後以同一個 tag 重跑 `deploy.sh`；要放棄這個版本，就照[版本回退](#版本回退)從第 2 步的備份還原。
- `docker compose ... run` 用的是發佈 checkout 的 `.env`，跟 `deploy.sh` 相同；指令裡不要印出環境變數（[本機檢查](WORKFLOW.md#本機檢查)的 env file 規則）。

## 版本回退

以 `deploy.sh <前一個 tag>` 部署回去，檢查與記錄相同；該 tag 的 image 還在時 build 走快取。資料庫 migration 不會跟著退：升級含 migration 的版本前照 [安全升級與復原順序](ops/SETUP.md#安全升級與復原順序) 先備份，回退時一併處理。DB 升到新 revision 之後，前一個 tag 的 api 會被 readiness 拒絕（它只接受自己的 head），daily 也無法執行（例如 0024 之後退回 `v1.2.0`）。所以要回退到 migration 之前的版本，只能先停 scheduler，用[含 migration 的版本](#含-migration-的版本)第 2 步的備份換回 volume 裡的 `stock.db`，再部署舊 tag；備份之後寫入的資料會遺失，要回補。

## V1 發佈隔離（G7 窗口專用）

只用於 V1 的 G7 窗口（使用者 2026-10-26 決定，#288）；窗口結束後不再使用，之後一律照上面的[流程](#流程)。窗口期間工作排程器從發佈 checkout 執行，發佈 checkout 跟著 `release/v1`，排程起跑前 `git pull --ff-only`（#314 前的 job）。

- **兩條 branch**：排程窗口期間發佈 checkout 跟發佈 branch `release/v1`（[排程](ops/SCHEDULING.md)），master 照常合併 V1.1。`release/v1` 受 ruleset 保護（禁止刪除與強推、只經 PR 以 merge commit 合併、CI `required` 綠）。
- **V1 改動兩個 PR**：要進 V1 的改動（V1 milestone 的 Issue，含窗口中的修正）從同一條工作 branch 開兩個 PR，一個進 master、一個進 `release/v1`，兩個都要 CI 綠；工作 branch 只合併 `origin/release/v1`（不合併含 V1.1 的 master），進 master 的衝突在 master 那個 PR 解。`release/v1` 不合回 master，也不拿它當 PR 的 head（合併後會被自動刪 branch 設定刪掉）。每次進 `release/v1` 記在 G7 Issue。
- **真資料 verify** 在窗口的開頭與結尾各跑一次，兩次都用當時 `origin/release/v1` 的程式：worktree 從它建、不加 commit、不留未 commit 的改動（`page_checks.py --g7` 要求 HEAD 等於 `origin/release/v1`，不符合就拒跑）；人工檢查由另一個 session 依寫死的樣本判讀，整份證據再由另一個 session 獨立 review。
- **每日核對**記發佈 checkout 當時的 branch 與 HEAD（`git -C <發佈 checkout> rev-parse --abbrev-ref HEAD` 與 `--short HEAD`），證明窗口每天跑的是 `release/v1`。
- **窗口結束**（使用者確認 G7 後）：`git log origin/master..origin/release/v1 --no-merges` 必須為空（V1 改動都已在 master）；在排程閒置時把發佈 checkout 切回 master、依 master 的 lock 檔重裝 venv（下一次 daily 會升 V1.1 的 migration）；`release/v1` 最後一個 commit 打 `v1.0` tag。三項結果記在 G7 Issue。

窗口結束後到 Docker 切換（#342）之前，工作排程器仍從發佈 checkout 執行，發佈 checkout 不能拉到含 #333 的 commit（[scheduler 容器的排程（serve）](ops/SCHEDULING.md#scheduler-容器的排程serve) 的切換前提）。上面的 `deploy.sh` 部署的是 image，只在 scheduler 容器接手之後使用；切換步驟與切換時的第一次部署見 [Docker 切換與回退（cutover.sh）](ops/platform/windows.md#docker-切換與回退cutoversh)（`tools/ops/cutover.sh`，#342）（正式 project 已有 #340 之前的容器在跑時，先停掉它們，見上面 exit 2）。`v1.0` 早於 #340，`deploy.sh` 的版本檢查會拒絕它。
