<!-- owns: 排程註冊與管理、Docker 切換與回退 -->
# Windows 工作排程器（只供回退）

本文只供回退：正式排程是 scheduler 容器的 `worker.cli serve`（[排程](../SCHEDULING.md)），Windows 工作排程器在 Docker 切換後停用、留作回退；切換與回退的步驟見 [Docker 切換與回退（cutover.sh）](#docker-切換與回退cutoversh)。

## daily／news 工作的註冊與管理

三個位置（使用者 2026-10-17 決定，見[排程](../SCHEDULING.md)開頭與[本機路徑](../LOCAL.md#正式位置使用者決定)）：

| 位置 | 路徑 | 說明 |
| --- | --- | --- |
| 資料目錄 | 正式資料目錄（[LOCAL](../LOCAL.md#正式位置使用者決定)）；scheduler 容器是 volume `stock-data` 的 `/data` | 正式 `stock.db`、`raw/`、`logs/`，與 job 的鎖 `locks/`。排程以 `--data-dir`（serve 傳 `/data`；工作排程器的註冊參數 `-DataDir`）傳入並設成 worker 子程序的 `STOCK_DATA_DIR`（預設依序為 `STOCK_DATA_DIR`、`~/stock-lab-data`），不由 cwd 推導。 |
| 發佈 checkout | 發佈 checkout（[LOCAL](../LOCAL.md#正式位置使用者決定)） | repo 的獨立 clone，停在部署的 tag（detached HEAD）；排程起跑不 `git pull`，master 合併的改動要打 tag、部署後才進排程。Docker 切換（#342）後它是正式 compose project 的目錄，只由 `tools/ops/deploy.sh <tag>` 改變：checkout tag、build 打 tag 的 image、`compose up -d`，部署記錄在 volume 的 `/data/logs/deploy.json`（[RELEASE](../../RELEASE.md#部署)，#340）。排程**只**從這裡執行，不從 `master` 管理 checkout 或任務 worktree。V1 G7 窗口期間的 `release/v1` 隔離見 [RELEASE](../../RELEASE.md#v1-發佈隔離g7-窗口專用)。 |
| Python | 發佈 checkout 的 venv（[LOCAL](../LOCAL.md#正式位置使用者決定)） | 工作排程器用：依 checkout 的 `backend/requirements.txt` 與 `backend/validation-requirements.lock.txt` 安裝。預設依序為 `-PythonPath`（別名 `-Python`）、`STOCK_PYTHON`、發佈 checkout 的 `.venv`。scheduler 容器用 image 內的依賴，`deploy.sh` 不碰 venv（#340）。 |

**scheduler 容器**：觸發與命令見 [scheduler 容器的排程（serve）](../SCHEDULING.md#scheduler-容器的排程serve)，部署見 [RELEASE](../../RELEASE.md#部署)。不經排程執行一次：`STOCK_RELEASE_TAG=<部署的 tag> docker compose -p <正式 project> exec scheduler python -m worker.cli job daily --trigger manual [--date YYYY-MM-DD] [--force]`（`--data-dir` 預設 compose 固定的 `STOCK_DATA_DIR=/data`，`--min-free-memory-gb` 預設 8，`claude` 用 image 的 PATH；news 同上換成 `job news`，另可加 `--skip-news-llm`，`--date` 只標記 run 日期）。停用與恢復見 [重跑與回補](../SCHEDULING.md#重跑與回補) 的 `stop scheduler`。

**工作排程器（切換前）**：首次建立：`git clone` 到發佈 checkout，checkout 要跑的 tag，建 `.venv` 並安裝依賴；以 SQLite backup API 把已初始化的 DB 複製成資料目錄的 `stock.db`（有 WAL 時不裸複製主檔），再於發佈 checkout 註冊工作。daily 開頭只在 DB 的 Alembic revision 不是程式 head 時才跑 `init_db`（含整庫 migration 完整性檢查，多年 DB 上要數分鐘）；已在 head 時直接開始。

以下命令在發佈 checkout 執行（`<py>` 為發佈 checkout 的 `.venv\Scripts\python.exe`，`<data>` 為資料目錄）：

| 動作 | 命令 |
| --- | --- |
| 預覽（不改系統） | `powershell -ExecutionPolicy Bypass -File tools/Register-WorkerSchedule.ps1 -Job daily -Python <py> -DataDir <data> -WhatIf`（news 把 `-Job` 換成 `news`；輸出的 `Command:` 列就是工作排程器會執行的完整命令，`WorkDir:` 是它的工作目錄 `backend`） |
| 註冊或更新 | 同上去掉 `-WhatIf`；同名覆寫 |
| 查詢 | `schtasks /query /tn "\stock-lab\daily" /v /fo list`；`Get-ScheduledTaskInfo -TaskPath \stock-lab\ -TaskName daily`（上次執行時間與結果、下次執行時間） |
| 手動觸發 | `Start-ScheduledTask -TaskPath \stock-lab\ -TaskName daily`（與排程完全相同的環境） |
| 停用／啟用 | `Disable-ScheduledTask -TaskPath \stock-lab\ -TaskName daily`／`Enable-ScheduledTask ...` |
| 移除 | `powershell -ExecutionPolicy Bypass -File tools/Register-WorkerSchedule.ps1 -Job daily -Unregister` |
| 不經排程執行一次 | 在 `backend` 目錄 `<py> -m worker.cli job daily --data-dir <data> --trigger manual [--date YYYY-MM-DD] [--force] [--claude-cli <claude.exe>]`（`--min-free-memory-gb` 預設 8）；news 另可加 `--claude-cli <claude.exe>`、`--skip-news-llm`，`--date` 只給 news（news-llm 的 `--date` 是篩選，不帶）。`tools/Invoke-WorkerJob.ps1` 只把舊參數（`-Job`、`-GitPull`、`-MinFreeMemoryGB`…）轉成這條命令，留給 #313 前註冊、還沒重新註冊的工作 |
| news 的 news-llm | 註冊 news 時指定 `-ClaudeCli <原生 claude.exe>`；未給時依序取 `STOCK_CLAUDE_CLI`、PATH 上第一個 `claude.exe`，都沒有或是 `.cmd` shim 就拒絕註冊。停用：同一條註冊命令改加 `-NoNewsLlm`（工作內為 `--skip-news-llm`）；恢復：去掉 `-NoNewsLlm` 再註冊一次。 |
| daily 的 candidate_notes | 註冊 daily 時加 `-ClaudeCli <原生 claude.exe>`（只認明確參數，不查 `STOCK_CLAUDE_CLI` 或 PATH；不存在或不是 `.exe` 就拒絕註冊），工作內以 `--claude-cli` 交給 job、再以 `STOCK_CLAUDE_CLI` 傳給 worker。未加時照常註冊，`Claude:` 列顯示 `(not set; …)`，該步驟依序用工作環境的 `STOCK_CLAUDE_CLI`、PATH 上的 `claude`，都找不到或找到的不是 `.exe` 就記 `cli_not_found`、不呼叫，daily 結果不受影響。 |

| 工作 | 觸發 | 動作 |
| --- | --- | --- |
| `\stock-lab\daily` | 週一至週五台北 18:30，21:30 再跑一次（`-TaipeiTimes` 可改） | `<py 同目錄的 pythonw.exe> -m worker.cli job daily --trigger scheduler --data-dir <data> --log-dir <data>/logs --min-free-memory-gb 2 [--claude-cli <claude.exe>]`（註冊參數 `-DailyMinFreeMemoryGB`、`-ClaudeCli`），單次上限 2.5 小時 |
| `\stock-lab\news` | 每天每 2 小時（`-IntervalHours`），從下一個整點區間開始 | 同上換成 `job news`、`--min-free-memory-gb 1`、`--claude-cli <claude.exe>`（註冊參數 `-NewsMinFreeMemoryGB`；`-NoNewsLlm` 時改為 `--skip-news-llm`）：先 `news`、再 `news-llm`，兩者合計單次上限 90 分鐘 |

工作排程器的兩個工作都以目前使用者、互動式登入、一般權限執行，不存密碼，使用者登入時才跑；錯過的時段在登入後補跑（StartWhenAvailable）。工作執行 `pythonw.exe`（沒有主控台視窗；venv 沒有時用 `python.exe`），job 再以 `python.exe` 無視窗啟動 worker。單一執行個體與單次上限由 job 保證（[日誌與 run 記錄](../SCHEDULING.md#日誌與-run-記錄)）；工作排程器另設「前一次未結束不另起」與比 job 上限多 10 分鐘的上限，當第二道防線。主機不在台灣時區時腳本自動換算本機時間。

休市日不寫進觸發：週間無交易日時官方來源回 no-data。當日目標第一次兩市都回 no-data（通常是 18:30）記 `non_trading_unconfirmed`，不算完成；21:30 再問一次仍是 no-data 才記 `non_trading_day`，這次有行情就照常跑完。目標日早於今日（手動補跑過去日期）時一次 no-data 即記 `non_trading_day`。三大法人與融資公布時間晚於收盤且不固定，18:30 若因缺這些資料而 collect 為 `partial`，analyze 不會執行，由 21:30 補齊；當日已 `success` 後的 21:30 記一列 `skipped`（`already_complete`），只再抓一次當日的兩份三大法人檔（[重跑與回補的冪等](../SCHEDULING.md#重跑與回補)），日線、融資、事件不再請求；已 `non_trading_day` 的日期什麼都不抓。

**單一執行個體與起跑前檢查**（job）：同一資料目錄的同種 job 以 `<data>/locks/<job>.lock` 的檔案鎖（`fcntl`）一次只跑一個，鎖由作業系統在 job 結束時釋放，被強制終止也不殘留；拿不到鎖記 `already_running`（daily 只在 DB 已是程式 head 時於 `schedule_runs` 留列；不是 head 時持鎖的 daily 可能正在 migrate，migration 在同一個交易裡先讀數分鐘再寫，期間別的連線寫入一列就會讓它失敗，所以只記日誌與 JSON 結果的 `error`）。拿到鎖後：可用實體記憶體（`/proc/meminfo` 的 `MemAvailable`，不用 WMI，#246）低於 `--min-free-memory-gb`（直接執行時預設 8；註冊時 daily 2、news 1）記 `low_memory`；這個 checkout 有 `index.lock` 或 `MERGE_HEAD` 記 `git_busy`（image 不含 `.git`，scheduler 容器裡不會發生）。這些都不執行 worker，等下一次觸發；daily 另在 `schedule_runs` 留一列 `skipped` 與原因，news 只寫日誌。全市場 analyze＋evaluate＋candidates＋indicators 峰值約 0.3 GB（[限制](../SCHEDULING.md#限制)），daily 門檻 2 GB 保留 collect 與其他程式的餘裕；2026-10-18 前註冊的工作仍是 6，要在發佈 checkout 重跑「註冊或更新」才生效。

**執行的版本**（#314、#340）：job 不更新程式，程式是 [`deploy.sh`](../../RELEASE.md#部署) 部署的 image。版本只有一套：image 的 `STOCK_IMAGE_TAG`（例如 `stock-lab-backend:v1.1.0`）與 `STOCK_GIT_HEAD`（該 tag 的 commit）。job 把兩者寫進日誌（`--- version image=<…> head=<…>`，沒有時 `unknown`），daily 記在 run 列的 `summary_json.runtime`（[日誌與 run 記錄](../SCHEDULING.md#日誌與-run-記錄)）；job 不執行 git。#314 前註冊的工作仍帶 `--git-pull`，job 照收、不 pull，日誌記一列 `--- --git-pull ignored`；重跑「註冊或更新」後就不再帶。

## Docker 切換與回退（cutover.sh）

[`tools/ops/cutover.sh`](../../../tools/ops/cutover.sh)（#342，決定 [6588843632](https://github.com/YiCheng0608/stock-lab/issues/342#issuecomment-6588843632)）把排程從工作排程器一次切到 scheduler 容器，`cutover.sh rollback` 切回。統籌在台北白天、避開偶數整點的 news 與 18:30～21:30 執行（[#1 6582767651](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-6582767651) 第 7 點），在 master 管理 checkout 以 Git Bash 跑（腳本在發佈 checkout 裡就拒絕）。每一步先印它執行的命令，最後印一列 JSON：`status` 是 `done`、`dry-run`、`refused` 或 `failed`，`steps` 是做完的步驟。`--dry-run` 只做檢查並列出全部步驟，不改工作排程器、checkout、資料目錄與 volume。結束碼：0 完成（或乾跑沒有問題）；1 拒絕，什麼都沒改；3 中途失敗，`steps` 列出已做的，以 `rollback` 復原；2／64 環境或參數錯誤。

**順序**（切換時段）：

1. 停用工作排程器的三個工作（工作帶 `-GitPull`，`feat/docker` 一進 master 就會被拉到 #333）：`Disable-ScheduledTask -TaskPath \stock-lab\ -TaskName daily`（news、watchdog 同），讀回 `Get-ScheduledTask -TaskPath \stock-lab\` 都是 `Disabled`、沒有 `Running`。
2. 合併 `feat/docker` 進 master（#420），等 merge commit 的 push CI（約 25 分），在它上面打 tag。
3. 開始前量正式 `raw/` 的大小（`du -sh <資料目錄>/raw`）並確認 Docker Desktop 的磁碟夠放 DB 快照與 `raw/` 兩份：#342 演練只搬了 73 MB，正式的 `docker cp` 與 `chown -R` 會久得多，時段要留足。也確認沒有從發佈 checkout `.venv` 常駐的程序（有的話 disable 那一步會等到逾時）。
4. `bash tools/ops/cutover.sh --dry-run --tag <tag>` 看檢查與步驟，再去掉 `--dry-run` 執行。失敗時（exit 3）照下面的「回退」以**同一組選項**（尤其 `--work-dir`）跑 `cutover.sh rollback`，不要只手動啟用工作：發佈 checkout 還在 master，下一個 job 的 `git pull` 會拉到 #333 並以 69 結束。切換的輸出（JSON 的 `steps`）留著：有沒有 `verify` 決定回退是 early 還是 full。
5. 第一次 daily 之後，把它的 `schedule_runs.summary_json.runtime` 與看門狗 `invariant_deploy_image` 貼在 #342 與 #331（#342 AC-4）。

**切換的檢查**（不符就拒絕，什麼都不改）：

- env file（`--env-file`，預設發佈 checkout 根目錄的 `.env`）這些 key 有值：`CLAUDE_CODE_OAUTH_TOKEN`、`GH_TOKEN`、`STOCK_WAKE_TOKEN`、`STOCK_MONITOR`、`STOCK_COORDINATION_DIR`（`--require-keys` 可改）；沒有 `ANTHROPIC_API_KEY`／`ANTHROPIC_AUTH_TOKEN`（[容器內的 claude 與 gh 認證（.env）](../SETUP.md#容器內的-claude-與-gh-認證env)）。以 `grep -q` 比對 key 那一行（`KEY=""` 這類空引號算沒有值），值不讀進腳本也不印出。
- 發佈 checkout 沒有未 commit 的改動；已含 #333（`d408ae7`）而仍有工作啟用時拒絕：那些工作會以 69 結束，排程已無聲停擺，先查原因（決定第 9 點）。
- `pre-docker` 要停的 commit（`--pre-docker`，預設發佈 checkout 的 HEAD）不能含 #333；工作在停用前已拉到 #333 時，以 `--pre-docker 0f99fea` 指定。
- 沒有工作在執行；project 的 `stock-data` volume 還不存在（volume 由 compose 在 volume 那一步建立，不用 `docker volume create`）；project 沒有容器在跑；資料目錄有 `stock.db`、`raw/`、`logs/`，`logs/` 裡沒有 `cutover.json`（它會被搬進 volume，回退會誤判切換已做完 verify）；Docker 能用。

**切換的步驟**：

| 步驟 | 做什麼 |
| --- | --- |
| pre-docker | 發佈 checkout 建本機 branch `pre-docker`（不 checkout），upstream 設成它自己（`branch.pre-docker.remote=.`、`branch.pre-docker.merge=refs/heads/pre-docker`），回退後 `git pull --ff-only` 回 up to date，不會被拉到 master（PR #420 review H1） |
| disable | 每個工作 `Disable-ScheduledTask`（已停用的照樣讀回），等到沒有工作在跑、也沒有發佈 checkout `.venv` 的程序（`stock.db` 沒有 writer），最多 `--wait-timeout` 秒（預設 900） |
| snapshot | `copy_db.py` 以 SQLite backup API 把 `stock.db` 複製到 `--work-dir`（預設 `<資料目錄>-cutover`，不能在資料目錄裡）的 `db/`，記各表列數；不裸複製有 WAL 的主檔（[安全升級與復原順序](../SETUP.md#安全升級與復原順序)） |
| volume | 以 master 管理 checkout 的 compose 檔 `compose run -d` 一個輔助容器（api 服務、root、`sleep`），compose 因此建立 `<project>_stock-data` 與它的 label；image `<project>-backend:cutover`，沒有就先 build（`compose run` 沒有 `--no-build`，image 已在就不會 build） |
| copy | `docker cp`：快照到 `/data/stock.db`、`raw/` 到 `/data/raw`、`logs/` 到 `/data/logs`；主機原檔保留 |
| chown | `chown -R 1000:1000 /data`：`docker cp` 寫入的是 root 的檔，image 以 uid 1000 執行（review M1） |
| verify | 以 uid 1000：`integrity_check` 是 ok、各表列數與快照相同（[`cutover_db.py`](../../../tools/ops/cutover_db.py)，結果的表數與總列數印在日誌）、`raw/` 的檔數與主機相同（`logs/` 不同只警告：統籌的心跳與壓縮紀錄在主機持續寫入）、`/data`、`stock.db`、`raw`、`logs` 都是 `1000:1000`；寫入 `/data/logs/cutover.json`（時間、來源、HEAD），回退以它為界取回新檔 |
| helper | 刪掉輔助容器，volume 留著 |
| start | `deploy.sh <tag>`（[RELEASE](../../RELEASE.md#部署)：checkout tag、build、部署記錄、`up -d --wait`、讀回、#1 留言；`--env-file`、`--web-port`、`--api-port`、`--no-comment` 傳給它），之後刪掉 `<project>-backend:cutover`。演練用 `--no-deploy`：以 master 管理 checkout 的 compose 檔與輔助 image 只起 api 與 scheduler |
| readback | `docker compose ls`、容器與 image、scheduler 日誌的 `serve ready`；在 scheduler 以 uid 1000 跑一次 `job news --trigger manual --skip-news-llm --min-free-memory-gb 1`（真的寫一次 DB 與日誌；`--no-write-check` 不跑），印出新檔的擁有者 |

**舊 raw 的路徑**（決定第 1 點，review H2）：`raw_payloads.payload_path` 是 capture 當時的絕對路徑，切換前是 `C:\Users\YiCheng\stock-lab-data\raw\...`。切換不改寫 DB，回退到 Windows 時舊路徑仍然有效。容器內讀 raw 的程式都經 [`app.raw_paths.payload_file`](../../../backend/app/raw_paths.py)：路徑存在就照用；不存在、且在舊資料目錄的 `raw` 底下（`\` 或 `/`，大小寫不拘）就讀 `STOCK_RAW_DIR`（compose 固定 `/data/raw`）下的同一相對路徑。看門狗的 data-check 把 `STOCK_RAW_DIR` 指到暫存目錄，舊路徑仍對應到真正的 raw（`STOCK_STORED_RAW_DIR`）。標的狀態同步讀不到行情 raw 時，記在該交易所 summary 的 `unreadable_quote_tables`（前 20 個 id 在 `unreadable_raw_payload_ids`），dormancy 記 `unverifiable`、原因 `unreadable quote table`，不再靜默略過。

**回退**（`cutover.sh rollback`，決定第 2 點；PR #424 review）：不論切換停在哪一步，最後都是發佈 checkout 在 `pre-docker`、`git pull --ff-only` exit 0、三個工作啟用。`pre-docker` 不存在時建在 `--pre-docker`（預設 HEAD，不能含 #333），upstream 設成它自己；已存在的不能含 #333，upstream 要是它自己（沒設就設）。對 DB 怎麼做，由一個唯讀掛 volume、跑完即刪的容器讀 `/data/stock.db` 與 `/data/logs/cutover.json` 決定；Docker 不能用時改看主機側的切換紀錄（見表下）：

| 方式 | 條件 | 步驟 |
| --- | --- | --- |
| early | 沒有 volume，或 volume 沒有 `cutover.json`（切換停在 verify 做完之前：停用後等待逾時、`copy_db.py`、image build、`compose run`、`docker cp` 失敗），serve 從沒在它上面跑過 | 主機 `stock.db` 不動，仍是正式 DB：helper（`docker rm -f` 輔助容器）、checkout、enable。手動停用工作後、還沒跑 cutover.sh 就放棄時也用這條（`pre-docker` 由它建立）。project 有 one-off 以外的容器卻沒有 `cutover.json` 時拒絕（狀態不明，人工確認） |
| full | volume 有 `cutover.json`：serve 可能寫過 volume | 下表 stop～enable。拒絕：有工作不是 `Disabled`（含 `Running`）；volume 沒有 `/data/stock.db`；主機 `stock.db` 或 `-wal` 在 `cutover.json` 的時間之後改過（有人寫過主機 DB，不以 volume 的取代） |
| resume | `<work>/rollback/installed.json` 記的是這次切換的 `cutover.json` 時間：前一次回退已裝回 DB、之後失敗（例如 `--start-news` 的 news 不是 0）；或 `installing.json` 記的是這次切換、主機 `stock.db` 與 `<work>/rollback/stock.db` 逐位元組相同（上一次回退在裝回之後、寫 `installed.json` 之前中斷，先補寫它） | 工作已啟用、Windows 可能已寫入主機 DB，不再取代：stop、checkout、enable。`installing.json` 記的是這次切換、但主機 `stock.db` 不同且在切換後改過時拒絕，訊息寫出原檔所在的 `backups/pre-rollback-*`，由人工判斷哪一份是正式 DB |

full 的步驟：

| 步驟 | 做什麼 |
| --- | --- |
| stop | `docker stop` project 所有在跑的容器（不 `down`，volume 留著） |
| snapshot | 以那個 image 起一個 uid 1000 的容器掛 volume，容器內 `copy_db.py` 取 `/data/stock.db` 的快照，`docker cp` 到 `<work>/rollback/stock.db`；比 `/data/logs/cutover.json` 新的 raw 取回主機的 `raw/`（已有的檔不覆寫），新的日誌取回 `<work>/rollback/logs/` |
| paths | 快照裡容器寫的 `payload_path`（`/data/raw/...`）改成主機 `raw/` 的同一檔（Windows 寫法），`pre-docker` 的程式照原路徑讀；`integrity_check` 要是 ok |
| install | 先寫 `<work>/rollback/installing.json`（這次切換的時間與備份目錄），再把資料目錄的 `stock.db`、`-wal`、`-shm` 搬到 `backups/pre-rollback-<UTC 時間>/`，快照成為 `stock.db`，記 `<work>/rollback/installed.json`（之後重跑就是 resume） |
| checkout | 發佈 checkout 的 `pre-docker`（見上），`git checkout pre-docker`，`git pull --ff-only` 必須 exit 0 |
| enable | 每個工作 `Enable-ScheduledTask` 並讀回；`--start-news` 另以 `Start-ScheduledTask` 跑一次 news、等它結束，`LastTaskResult` 要是 0 |

**Docker 不能用時**（找不到 docker、`docker compose` 不能執行，或 daemon 60 秒內沒有回應：切換常因 Docker Desktop／WSL 掛掉而失敗）：讀不到 volume，改看切換開始時與每做完一步就寫的主機側紀錄 `<work>/cutover-steps.json`（project、時間、`steps`）。紀錄的 `steps` 沒有 `verify`（serve 沒跑過）就走 early、完全不碰 Docker：checkout、enable，輔助容器與 volume 等 Docker 回來再處理。紀錄有 `verify`（serve 可能寫過 volume）或沒有紀錄（這個 `--work-dir` 沒跑過切換，或選項不同）時拒絕：先讓 Docker 回來再跑 rollback。Docker 正常時若紀錄有 `verify`、volume 卻沒有 `cutover.json`，也拒絕（狀態不明）。切換本身在 Docker 不能用時 exit 2，什麼都不改。

- **紀錄只算一次**：回退（任一方式）做完時，把紀錄改名歸檔為 `<work>/cutover-steps.rolled-back-<UTC>.json`。Docker 不能用時，回退只接受還沒歸檔的紀錄；只有歸檔過的就拒絕，因為之後的切換可能用了別的 `--work-dir`，serve 可能寫過它的 volume。切換開始時，若 `--work-dir` 裡有還沒歸檔的紀錄也拒絕：先回退那次切換；確定已處理完時，手動改名歸檔。
- **Docker 不能用而走 early 之後**：Docker 回來時，用同一組選項再跑一次 `cutover.sh rollback`。
  - volume 沒有 `cutover.json`：照 early 刪掉輔助容器（checkout、enable 照做，結果不變）。
  - volume 已有 `cutover.json`：切換在寫完它、還沒記 `verify` 時中斷。這時 full 會因工作已啟用而拒絕，但 serve 沒跑過，主機 DB 才是正式的。
  - 兩種情況下 volume 都留著；要再切換時，由使用者確認後執行 `docker volume rm <project>_stock-data`。
- **已裝回（有 `installed.json`）之後 Docker 才掛掉**：紀錄有 `verify`，回退會拒絕。等 Docker 回來，用同一組選項再跑，就是 resume（stop、checkout、enable）。容器先前已 `docker stop`，`restart: unless-stopped` 不會自己起來，等待期間不會有兩邊同時寫 DB。
- **install 中斷**：重跑時，若 `installing.json` 記的是這次切換，回退先印一行「比對中」，再逐位元組比對主機 `stock.db` 與快照（數 GB 要幾分鐘）。若主檔已搬進備份、`-wal`／`-shm` 還在主機，就沿用 `installing.json` 的備份目錄，讓原 DB 的檔留在同一處。備份目錄已有同名檔時拒絕，不覆寫。

回退後 volume、image 與停止的容器都留著，刪不刪由使用者決定。**volume 建立之後失敗就不能重跑切換**：切換只寫入 compose 新建的 volume，舊的在就拒絕；`docker volume rm <project>_stock-data` 會被 hook 擋（[AGENTS](../../../AGENTS.md#規則與強制手段)），由使用者確認裡面沒有要留的資料後自己刪，再從頭切換。

切換在 start 之後失敗（讀回：`serve ready` 沒出現、news job 不是 0）時，部署本身已完成，腳本會這樣提示：先查原因（偶數整點 serve 自己的 news、記憶體），不要直接回退。

**演練**：用正式 DB 的副本（`copy_db.py`）、只含幾個交易日 raw 的測試資料目錄、發佈 checkout 的 clone、測試用的工作排程器資料夾（例如 `\t342\`，工作的動作是無害的命令）與 `t<issue>` 開頭的 project，以 `--checkout`、`--data-dir`、`--work-dir`、`--task-path`、`--project`、`--env-file <替身>`、`--no-deploy` 指定。正式的 `\stock-lab\` 只跑 `--dry-run`。檢查、乾跑、切換在各步失敗後的回退與三種回退方式的測試是 `backend/tests/test_cutover.py`（假 docker、假 PowerShell）。
