<!-- owns: macOS 主機的需求與設定、OrbStack 沒開的判讀、正式環境所在主機、Windows 與 macOS 之間的搬遷 -->
# macOS 主機（Intel）

服務、排程與測試都在 Linux 容器裡（[環境、啟停與資料庫](../SETUP.md#工作目錄環境與啟停)），換主機不必改程式。本文只寫 macOS 主機跟 Windows 主機（Git Bash＋Docker Desktop，[SETUP](../SETUP.md#工作目錄環境與啟停)；停用的工作排程器見 [Windows 工作排程器](windows.md)）不一樣的地方。兩種主機都要能照手冊工作（使用者 2026-11-21 決定，[#1 7058347984](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-7058347984)）：共用不了的才在這裡另寫，Windows 的做法保留。

## 正式環境所在主機

| 項目 | 現況 |
| --- | --- |
| 正式環境（正式 compose project、scheduler） | macOS Intel 主機（使用者 2026-11-21 決定）。同一時間只有一台跑正式 scheduler：另一台的正式 project 停掉（`docker compose -p stock-lab stop`），volume 留著 |
| 備援 | Windows 主機。做法與文件保留；要切回時照[搬遷](#windows-與-macos-之間的搬遷)反方向做 |
| CPU 架構 | 兩台都是 x86_64（amd64），跟 CI 的 ubuntu runner 一樣，image 不用另外 build 別的架構 |

## 主機需求

| 項目 | macOS 的做法 | 為什麼 |
| --- | --- | --- |
| Docker | [OrbStack](https://orbstack.dev)（`docker context ls` 的 `orbstack`）。記憶體上限 `orbctl config set memory_mib 6144`（6 GB），改完要重開 OrbStack（`orbctl stop` 再 `orbctl start`）。登入時啟動：`orbctl config set app.start_at_login true` | 上限的理由跟 Windows 的 `.wslconfig` `memory=6GB` 一樣（[Docker compose](../SETUP.md#docker-compose)）。2026-11-21 在 8 GB RAM 的主機上實測 `docker info` 的 MemTotal 是 5.86 GiB |
| bash 4.1 以上 | MacPorts：`sudo port install bash`。`/opt/local/bin` 要排在 PATH 的 `/bin` 前面（MacPorts 安裝時會寫進 shell 設定檔） | `/bin/bash` 是 3.2，沒有 `mapfile`、`coproc`、`{fd}` 重導；`coordinator_lib.sh` 碰到 4.1 以下就 exit 2 並說明原因 |
| `timeout` | MacPorts：`sudo port install coreutils`。裝的是 `gtimeout`，`coordinator_lib.sh` 會自動改用它 | docker、Orca、codebase-memory 的呼叫都有時間上限 |
| Python 3.12 以上 | MacPorts：`sudo port install python312`（`python3.12`）。`find_python` 會先找 `python3.12`，再找 `python3` | `/usr/bin/python3` 是 3.9；`coordinator_json.py` 要 3.12（`DirEntry.is_junction`） |
| gh | MacPorts：`sudo port install gh`，再由使用者自己 `gh auth login` | 主機端的腳本與統籌都用它 |
| Orca | `/Applications/Orca.app`。CLI 在 `/Applications/Orca.app/Contents/Resources/bin/orca`，Orca 會把它放進 PATH；PATH 上找不到時，`monitor.sh`、`orca_wake.sh`、`wake_listener.py` 也會去這個位置找 | |
| 不睡眠 | 插電時不睡：`sudo pmset -c sleep 0 disksleep 0`（螢幕照常關） | 主機睡著時 OrbStack 的容器跟著停，daily、news、看門狗都不會跑 |

其他工具（git、node、claude）照一般安裝；路徑見 [LOCAL「工具」](../LOCAL.md#工具)。

**筆電要注意**：蓋上螢幕還是會睡（除非接著電源與外接螢幕）。正式環境的 MacBook 要開著螢幕蓋，或接外接螢幕使用。
- **只有內建螢幕時，螢幕要保持開著**：使用者 2026-11-22 決定不改 `pmset`（[#1 7072447929](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-7072447929)）。
  - 闔上會進 Clamshell Sleep，排程全停；`sleep 0` 與 `caffeinate` 都擋不住。
  - 2026-11-22 01:45～09:34 就因為闔上，news 漏了 4 輪。
- **查現況**：`ioreg -r -k AppleClamshellState` 讀感應器。快闔上、還沒全闔，也可能判成闔上。
- **排程有空窗時**：先查 `pmset -g log | grep -E 'Clamshell|LidOpen'`。是闔上造成的，就照 [SCHEDULING](../SCHEDULING.md) 補跑。

**記憶體門檻看容器，不看主機**：主機 8 GB，OrbStack 的 VM 占 5.86 GiB，主機端的空閒最多約 4.7 GiB。文件寫「空閒記憶體 ≥ 5 GB」的地方（研究工具、[月報的每月流程](../../spec/evidence.md#前瞻驗證-h1)），在這台都改量容器內的可用記憶體：`docker run --rm --network none alpine grep MemAvailable /proc/meminfo`。2026-11-22 量到約 5.0 GiB（#953 決定 [7073872883](https://github.com/YiCheng0608/stock-lab/issues/953#issuecomment-7073872883)）。門檻在這台是 **MemAvailable ≥ 4.8 GiB（5,033,165 kB）**，不是 5 GiB（#1006 統籌承諾 [7108278163](https://github.com/YiCheng0608/stock-lab/issues/1006#issuecomment-7108278163)）：

- **量到的基線**：VM 的 MemTotal 6,139,564 kB；#986 量到 5.00～5.01 GiB、#1000 4.86～4.92 GiB、#1008 4.85～4.88 GiB（起跑前只有 api、scheduler、web 在跑），5 GiB 常等不到；#1000 的探索段、#1008 的 `--coverage-only` 都是一次性放寬到 4.8 GiB 起跑。
- **用量**：研究容器上限 `--memory 4g --memory-swap 4g`，這台實測峰值 #1000 探索段 1.97 GB、#1008 `--coverage-only` 1.44 GB，都沒有被殺；4.8 GiB 扣掉 4 GiB 的上限還留約 0.8 GiB 給正式容器。
- **其他條件不變**：容器上限、探索段與 `--coverage-only` 加 `--oom-score-adj 1000`、驗證段不加、同時只跑一個研究工具、時段，照 [RESEARCH_DB「研究工具的耗時與記憶體」](../RESEARCH_DB.md#研究工具的耗時與記憶體)與[第 2 步的工具](../../spec/evidence.md#第-2-步的工具)。

## 跟 Windows 不一樣的地方

| 項目 | Windows（Git Bash） | macOS |
| --- | --- | --- |
| `docker -v` 的路徑 | 要 `MSYS_NO_PATHCONV=1`，否則 Git Bash 會改寫容器路徑；`pwd -W` 取 `C:/…` 寫法 | 不用改寫，`MSYS_NO_PATHCONV` 設了也沒有作用；用 `pwd` |
| 工程師 terminal 的 shell | `dispatch.sh` 帶 `--shell git-bash` | 不帶 `--shell`（Orca 在 macOS 拒絕這個選項），用登入 shell（zsh）；`COMPOSE_PROJECT_NAME=… claude …` 這種前綴在 zsh 也是同樣寫法 |
| 檔名大小寫 | NTFS 不分 | APFS 預設也不分；`agent_guard.cjs` 比對記憶目錄時兩邊都不分大小寫 |
| 容器連主機的 wake listener | Docker Desktop 把 `host.docker.internal` 代理到主機的 `127.0.0.1` | OrbStack 也一樣：2026-11-21 實測，容器連得到主機上只綁 `127.0.0.1` 的服務（[統籌事件 monitor](../MONITOR.md)）|
| 停止 wake listener | `Stop-Process -Id (Get-NetTCPConnection -LocalPort 47338 -State Listen).OwningProcess` | `kill $(lsof -t -nP -iTCP:47338 -sTCP:LISTEN)`；`wake_listener_start.sh` 會依主機印出對的那一條 |
| wake listener 的生命週期 | 跟著啟動它的統籌 terminal 結束；換手時 `take_over.sh` 等它結束再起新的 | 改掛 launchd、活過 terminal；換手時 `take_over.sh` 認出是本 checkout 的才停掉重起，認不出就停下（[統籌事件 monitor「生命週期」](../MONITOR.md)） |
| Claude Code 的 scratchpad | `$TEMP/claude/<專案>/<session id>` | `/private/tmp/claude-<uid>/<專案>/<session id>`；`close_task.sh` 兩種都會清 |
| dev 的 bind mount | 沒有檔案事件，api 與 web 靠輪詢 | OrbStack 有檔案事件；輪詢的設定留著也沒關係 |
| 容器外的 venv | `.venv/Scripts/python.exe`，套件在 `.venv/Lib/site-packages`，`PYTHONPATH` 用 `;` 分隔 | `.venv/bin/python`，套件在 `.venv/lib/python3.12/site-packages`，`PYTHONPATH` 用 `:` 分隔 |

### OrbStack 沒開

- **判讀**：`docker info --format '{{.ServerVersion}}'` 與任何 `docker compose` 命令都失敗，訊息是 `Cannot connect to the Docker daemon at unix:///Users/<使用者>/.orbstack/run/docker.sock`。`orbctl status` 會印 `Stopped`。
- **期間**：跟 [Docker Desktop 沒開](../SETUP.md#docker-desktop-沒開)一樣：沒有排程、沒有看門狗留言，統籌 `patrol.sh` 印的 monitor 心跳不再前進。
- **恢復**：開 OrbStack（`orbctl start` 或開 App）。三個服務都是 `restart: unless-stopped`，OrbStack 起來後會自己回來。

## Windows 與 macOS 之間的搬遷

下面以「舊主機」「新主機」稱呼，兩個方向的步驟相同。資料只在 Docker volume 裡（`stock-lab_stock-data`，研究 DB 在 `stock-lab-research`，[RESEARCH_DB](../RESEARCH_DB.md)），所以搬遷就是把 volume 的內容搬過去，再在新主機部署同一個 tag。刪除正式資料、部署、停舊主機的 project 都要使用者同意。

1. **舊主機停止寫入**：開維護模式，確認 `running_jobs` 是 `[]`（[維護模式](../SCHEDULING.md#維護模式)）。
   - `docker compose -p stock-lab exec scheduler python -m worker.cli maintenance on --reason "<搬遷原因>"`
   - `docker compose -p stock-lab exec scheduler python -m worker.cli maintenance status`
   - 記下正在跑的 tag：`docker inspect -f '{{.Config.Image}}' stock-lab-api-1`。
2. **舊主機取快照**：
   - DB 用 `copy_db.py` 取一致副本（[取正式 DB 的唯讀副本](../LOCAL.md#取正式-db-的唯讀副本)）。`copy_db.py` 的輸出一律叫 `stock.db`，所以正式與研究 DB 的副本放不同目錄（例如 `$B/prod`、`$B/research`）。
   - volume 的其他內容（`raw/`、`logs/`、`locks/` 裡的維護標記）用唯讀掛載打包，例如 `docker run --rm --network none -v stock-lab_stock-data:/data:ro -v "$B":/out <image> tar -C /data --exclude=./stock.db --exclude=./stock.db-wal --exclude=./stock.db-shm -czf /out/stock-data.tgz .`（`$B` 是備份目錄，[LOCAL](../LOCAL.md#正式位置使用者決定)；Windows 要加 `MSYS_NO_PATHCONV=1`）。研究 volume（`stock-lab-research`）同樣做，輸出另取檔名。
   - 統籌的協作目錄 `~/stock-lab-data/logs`（心跳、事件佇列）一起帶走。
3. **搬檔**：由使用者自己搬（雲端硬碟、外接碟）。`.env` 不搬也不經 agent，由使用者在新主機自己建（[容器內的 claude 與 gh 認證](../SETUP.md#容器內的-claude-與-gh-認證env)）。
4. **新主機還原 volume**：先建帶 compose 標籤的 volume，compose 才會把它當成自己的：
   - `docker volume create --label com.docker.compose.project=stock-lab --label com.docker.compose.volume=stock-data stock-lab_stock-data`
   - 解開 `stock-data.tgz` 到 volume，再把 DB 副本放成 `/data/stock.db`。新建的 volume 是 root 擁有，所以以 root 寫入，最後 chown 給容器使用者 1000（同 [建研究 DB](../RESEARCH_DB.md#建研究-db)）：`docker run --rm --network none -u 0 -v stock-lab_stock-data:/data -v "$B":/in:ro <image> sh -c 'tar -C /data -xzf /in/stock-data.tgz && cp /in/prod/stock.db /data/stock.db && chown -R 1000:1000 /data'`。
   - 研究 volume 不屬於 compose project，直接 `docker volume create stock-lab-research`，其餘同上（DB 用 `$B/research/stock.db`）。
   - 還原完對 volume 裡的 DB 跑一次 `copy_db.py`（輸出的 `quick_check` 要是 `ok`），並核對 `alembic_version` 與 `source_latest_trading_date` 跟舊主機的一樣。
5. **新主機部署**：
   - `git clone git@github.com:YiCheng0608/stock-lab.git ~/stock-lab-release`，`.env` 由使用者建，`STOCK_COORDINATION_DIR` 填這台的 `~/stock-lab-data/logs`，要寫成絕對路徑。
   - 從管理 checkout 執行 `bash tools/ops/deploy.sh <第 1 步記下的 tag>`（[部署](../../RELEASE.md#部署)）。
   - 快照裡有第 1 步開的維護標記。`deploy.sh` 核對通過後會自己把它關掉（部署記錄的 `maintenance` 是 `turned_off`），新主機的排程從下一個觸發開始。
6. **停舊主機**：使用者同意後，在舊主機執行 `docker compose -p stock-lab stop`。不加 `down -v`，volume 留著，要切回時可以用。舊主機的 Orca、統籌 session 也結束，只留新主機的統籌。
7. **驗證**：在新主機跑 [verify-stock-lab 真資料模式](../../../.claude/skills/verify-stock-lab/SKILL.md#真資料模式)；下一次 daily、news 跑完後看門狗沒有警報。
