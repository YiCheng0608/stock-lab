<!-- owns: 工作目錄與環境、服務啟停、Docker Desktop 沒開的判讀、API 跨站請求防護、資料庫 migration 與 readiness、Alembic head、容器內的 claude 與 gh 認證 -->
# 環境、啟停與資料庫

本文件只保留可操作入口、安全邊界與診斷順序；本機檢查命令見[工作手冊](../GITHUB_WORKFLOW.md#本機檢查)，能力狀態見 [ROADMAP](../ROADMAP.md)。

## 工作目錄、環境與啟停

服務、測試與排程都在容器裡執行（#331）：api、web、scheduler 由 compose 啟動（[Docker compose](#docker-compose)），資料在 named volume `stock-data`，排程是 scheduler 容器的 `worker.cli serve`（[scheduler 容器的排程（serve）](SCHEDULING.md#scheduler-容器的排程serve)），本機檢查也在容器內跑（[工作手冊](../GITHUB_WORKFLOW.md#本機檢查)）。主機只需要 Docker Desktop（WSL 2 backend）與 Git Bash；Docker Desktop 沒開時的判讀見 [Docker Desktop 沒開](#docker-desktop-沒開)。正式排程切到容器（#342）之前，Windows 工作排程器仍從發佈 checkout 跑 #333 以前的 commit（[排程](SCHEDULING.md)）。

容器外（選用）：後端命令也能在主機的 venv 從專案根目錄執行，用在單次的 API 或 worker 命令；`worker.cli job`、`serve` 與 `python -m worker.job lock` 只在 Linux 執行，在 Windows 以 exit 69 拒絕，所以排程與看門狗的鎖不能在主機跑。範例預設使用 workspace 內 `.local` 開發資料；做測試、migration 或可丟棄研究時，先把三個 `STOCK_*` 改成明確的隔離路徑，不指向正式 `data/stock.db`。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt

$env:STOCK_DATA_DIR = (Join-Path $PWD '.local/data')
$env:STOCK_DB_PATH = (Join-Path $env:STOCK_DATA_DIR 'stock.db')
$env:STOCK_RAW_DIR = (Join-Path $env:STOCK_DATA_DIR 'raw')
$env:PYTHONPATH = (Join-Path $PWD 'backend')

python -m worker.cli init-db   # 明確初始化／升級指定 DB 後再啟動 API
python -m uvicorn app.main:app --reload --port 8000
```

**後端 image**（#333，母單 #331）：[`backend/Dockerfile`](../../backend/Dockerfile) 是 api 與 scheduler 共用的 image，從 repo 根目錄 `docker build -f backend/Dockerfile -t stock-lab-backend .`。內含 Python 依賴（`backend/requirements.txt`＋lock）、CI repository job 的 ruff 與 PyYAML（同版本，本機檢查用，#339）、`tzdata`（`TZ=Asia/Taipei`）、git、`gh`、Node 22、Claude Code CLI（`~/.claude.json` 已標記 onboarding 完成）與 Chromium＋CJK 字型（`tools/ops/screenshot.cjs` 用，`SCREENSHOT_BROWSER=/usr/bin/chromium`）；以非 root 使用者 `app` 執行，PID 1 是 `tini`（回收被殺 job 留下的孤兒程序，否則 zombie 的 PID 看起來仍在、run 列不會立即記 abandoned），`STOCK_DATA_DIR=/data`，`PYTHONPATH=/app/backend`。image 本身不帶啟動命令，api 與 scheduler 的命令由 compose 給（[Docker compose](#docker-compose)）。build context 排除的檔案見根目錄 `.dockerignore`（含 `.git`）；測試讀 git 歷史，所以容器內跑測試時把 checkout 的 `.git` 唯讀掛進去：`docker run --rm -v "$PWD/.git:/app/.git:ro" stock-lab-backend pytest backend/tests -q`（CI `docker` job 的命令與此相同，但只跑 [`tools/ci/docker_suite.json`](../../tools/ci/docker_suite.json) 列的測試，全套在 `backend` job，見[工作手冊](../GITHUB_WORKFLOW.md#review-與合併)）。執行層（`worker.job` 的 `job` 與 `lock`）只在 Linux 執行，其他系統以 exit 69 拒絕。

`init-db` 會改 schema，執行前先解析三個路徑並為既有 DB 備份（[安全升級與復原順序](#安全升級與復原順序)）。API startup 只跑 `check_database_readiness()`，不會自動建庫、migration、repair 或 stamp；缺檔、空檔、不可讀或不符契約時拒絕啟動。已啟動的 process 不會因 source 更新而改變 lifespan。

`app.config` import 執行設定的 data／raw 目錄建立；API 的資料變更 handlers 及 collect／daily／backfill／analyze／evaluate／backtest／news／news-llm 是寫入入口。要做只讀查驗，應直接使用 SQLite `mode=ro`＋`PRAGMA query_only=ON`，不能用一般 app startup 代替。`GET /api/dashboard`、`GET /api/news`、`GET /api/news/{id}` 會呼叫 `sync_news_from_events`，把本機既有官方 Events 冪等投影成 NewsItem 並 commit。前端開發服務與 `VITE_API_BASE` 見[前端 README](../../frontend/README.md#啟動)。

### 產品 API 的跨站請求防護

`app.main:app` 對每個 POST、PUT、PATCH、DELETE，先經 [`BrowserGate`](../../backend/app/browser_gate.py)（純 ASGI，常開，沒有關閉或繞過的設定）才進 router；GET、HEAD、OPTIONS 不檢查。拒絕的請求不讀 body、不開 DB。CORS 只決定瀏覽器讀不讀得到回應，不阻止表單或 `text/plain` 的 simple request 送達本機埠，所以需要這層。四項依序檢查，第一個不符即回應：

| 順序 | 檢查 | 放行條件 | 拒絕 |
| --- | --- | --- | --- |
| 1 | Host | 恰一個值，為小寫 `127.0.0.1:<port>` 或 `localhost:<port>`，`<port>` 是 API 實際監聽埠；或完全等於 `STOCK_API_PUBLIC_HOSTS` 列的一個值。API 都要在 TCP 埠上監聽 | 403 `host_not_admitted` |
| 2 | Sec-Fetch-Site（有送時） | `same-origin`、`none` 放行；`same-site`、`cross-site` 僅在 Origin 已被接受時放行 | 403 `cross_site_rejected` |
| 3 | Origin（有送時） | 在允許清單內，或等於自身 `http://<Host>`。允許清單是 `config.DEFAULT_CORS_ORIGINS`（`http://localhost:5173`、`http://127.0.0.1:5173`）加上 `STOCK_API_ALLOWED_ORIGINS` 列的值 | 403 `origin_not_admitted` |
| 4 | Content-Type（只查 POST、PUT、PATCH） | `application/json`，可接 `; charset=utf-8` | 415 `content_type_json_required` |

拒絕回應是 JSON `{"reason":"<reason>"}` 加 `Cache-Control: no-store`；防護在 `CORSMiddleware` 內側，允許清單內的 origin 被拒時前端仍讀得到狀態碼與 reason。沒有 Origin 與 Sec-Fetch-Site 的請求（curl、腳本）只受 Host 與 Content-Type 規則約束（POST 須帶 `-H "Content-Type: application/json"`）。

允許清單另可由兩個環境變數加值（[`app.config`](../../backend/app/config.py) 的 `public_hosts`、`allowed_origins`；範例見 [`.env.example`](../../.env.example)）。沒設、或值是空白時，行為與沒有這兩個變數時完全相同：

| 變數 | 加到哪一項 | 每個值的格式 | 用途 |
| --- | --- | --- | --- |
| `STOCK_API_PUBLIC_HOSTS` | Host | `localhost:<port>` 或 `127.0.0.1:<port>` | 瀏覽器看到的 API 埠不是監聽埠：nginx 反代 `/api` 並轉送瀏覽器的 Host（`proxy_set_header Host $http_host`），或容器埠對映到另一個主機埠 |
| `STOCK_API_ALLOWED_ORIGINS` | Origin 允許清單與 CORS（`configure_cors`，同一份清單） | `http://localhost:<port>` 或 `http://127.0.0.1:<port>` | 前端開發服務不在 5173（例如 dev 換 `WEB_PORT`） |

多個值以逗號分隔，前後空白會去掉。`<port>` 是 1～65535、不補前導 0，而且一定要寫：瀏覽器連 80 埠時送出的 Host 不帶 port，列不進清單，寫入會被拒，所以反代或前端對外的埠（`WEB_PORT`）不能用 80。主機名只收小寫的 `localhost` 與 `127.0.0.1`。萬用字元、空項目、`https` 或其他 scheme，以及帶 path、query、fragment、userinfo 的值都不接受。值不符時，`app.main` 匯入就丟 `ValueError`，訊息寫出變數名與那個值，API 不會啟動。worker 不讀這兩個變數。Host 與 Origin 各自比對：列在 `STOCK_API_ALLOWED_ORIGINS` 的埠不會因此成為可接受的 Host，反之亦然。由同一個反代送出的頁面，Origin 等於自身 `http://<Host>`，不必再列進 `STOCK_API_ALLOWED_ORIGINS`。

寫入會被拒的情況：以 LAN IP、機器名稱、IPv6 `[::1]` 或經代理改寫的 Host 連線（例如反代沒轉送 Host，API 看到 `api:8000`）；Host 大小寫變體，或 port 不符、省略且不在 `STOCK_API_PUBLIC_HOSTS`；Unix socket；`VITE_API_BASE` 不符 Host 規則；前端開發服務改用 5173 以外的埠，而該 origin 不在 `STOCK_API_ALLOWED_ORIGINS`。這不是身分驗證，同機其他程式送出符合規則的請求一樣放行。

### Docker compose

（#335，母單 #331）根目錄的 [`docker-compose.yml`](../../docker-compose.yml) 是基底，[`docker-compose.dev.yml`](../../docker-compose.dev.yml) 是開發 override。從 repo 根目錄執行，需要 Docker Compose 2.24 以上（`env_file` 的 `required: false`）。

| 服務 | image（以 project 名稱開頭） | 命令 | 主機埠（只綁 `127.0.0.1`） | `mem_limit` | 健康檢查 |
| --- | --- | --- | --- | --- | --- |
| api | `<project>-backend:<STOCK_RELEASE_TAG>`（[後端 image](#工作目錄環境與啟停)；tag 預設 `latest`） | `uvicorn app.main:app --port 8000`；dev 加 `--reload` | `API_PORT`（預設 8000）→ 8000 | 1 GB | `GET /api/health` |
| web | `<project>-web:<STOCK_RELEASE_TAG>`（nginx，[前端 image](../../frontend/README.md#docker-image)）；dev 是 `<project>-web-dev`（Vite） | nginx，`/api` 反代到 `api:8000`；dev 是 `pnpm run dev`，直接呼叫 `API_PORT` | `WEB_PORT`（預設 8080）→ 8080 | 256 MB；dev 1 GB | `GET /` |
| scheduler | 同 api | `python -m worker.cli serve`（[scheduler 容器的排程（serve）](SCHEDULING.md#scheduler-容器的排程serve)）；另 bind mount `STOCK_COORDINATION_DIR` 到 `/coordination`（[統籌事件 monitor](MONITOR.md)） | 無 | 2 GB | 無（serve 結束時容器跟著結束、自動重啟） |

三個服務都是 `restart: unless-stopped`、`TZ=Asia/Taipei`。api 與 scheduler 以 tini 執行 [`backend/docker/entrypoint.sh`](../../backend/docker/entrypoint.sh) 再接命令。資料目錄是 named volume `stock-data`（容器內 `/data`：`stock.db`、`logs/`、`exports/`），不 bind mount；`STOCK_DATA_DIR`、`STOCK_DB_PATH`、`STOCK_RAW_DIR` 由 compose 固定成 `/data` 下的路徑，env file 裡的值蓋不過去。scheduler 不設固定 `hostname:`：abandoned 改以鎖判定（[日誌與 run 記錄](SCHEDULING.md#日誌與-run-記錄)），固定 hostname 反而會讓沒帶鎖的列以主機＋PID 跨 PID namespace 判定（#336 review 建議 3）。

| 用途 | 命令 |
| --- | --- |
| 開發 | `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build`：bind mount 整個 checkout，api 以 `uvicorn --reload`、web 以 Vite HMR 即時套用修改（Windows bind mount 不送檔案事件，兩者都以輪詢偵測：`WATCHFILES_FORCE_POLLING`、`CHOKIDAR_USEPOLLING`）。`stock-data` 沒有 `stock.db` 時，api 啟動前寫入 verify 假資料庫（`tools/verify/fixture_db.py`）；已有的 `stock.db` 不動。scheduler 只在加 `--profile scheduler` 時啟動，開發用的 checkout 不會自己跑 daily、news |
| 正式拓撲 | `docker compose up -d --build`：web 經 nginx 服務 build 好的頁面。api 在空的 `stock-data` 上會拒絕啟動（[資料庫、migration 與 readiness](#資料庫migration-與-readiness)），要先 `docker compose run --rm api python -m worker.cli init-db`，或把 `copy_db.py` 做的副本放進 volume |
| 後端測試、lint、前端測試與 build | `docker compose -p task-<issue> run --rm …`，命令與容器內 git 的掛法見[工作手冊「本機檢查」](../GITHUB_WORKFLOW.md#本機檢查)（#339） |
| 狀態與停止 | `docker compose ps`（健康狀態）、`docker compose logs <服務>`、`docker compose down`（`--volumes` 會連 `stock-data` 一起刪；agent 的 hook 只放行以 `-p` 寫明測試 project 的 `down -v`，[AGENTS](../../AGENTS.md#規則與強制手段)） |

**變數**（從 shell 或根目錄 `.env` 讀，見 [`.env.example`](../../.env.example)）：

- `WEB_PORT`、`API_PORT`：主機埠。api 的 `STOCK_API_PUBLIC_HOSTS` 由 compose 設成 `localhost`／`127.0.0.1` 加這兩個埠；dev 另把 `STOCK_API_ALLOWED_ORIGINS` 設成 `WEB_PORT` 的兩個 origin（[產品 API 的跨站請求防護](#產品-api-的跨站請求防護)）。entrypoint 以 exit 64 拒絕三種值：`WEB_PORT`、`API_PORT` 是 80（瀏覽器在 80 埠送的 Host 不帶埠，寫入一律被拒）；`WEB_PORT` 是 8000（api 的監聽埠，即使沒有允許清單 Host `localhost:8000` 也會放行，PR #349 review S2）；兩者相同。空值視為沒設：scheduler 只從 env file 拿到這兩個變數，`.env` 裡的 `WEB_PORT=` 不會讓它停下（#335 review S7）。
- `-p <project>`：project 名稱，預設是目錄名。image、容器、網路與 volume（`<project>_stock-data`）都以它開頭，所以兩個 worktree 各用自己的 project 與埠就能同時 `up` 或 `run`，互不影響。
- `STOCK_ENV_FILE`：api 與 scheduler 的 env file，預設根目錄 `.env`。使用者手動建立、不進 Git（#337）；agent 不讀它的內容。檔案不存在時照常啟動，只是沒有 token，`claude -p` 與 `gh` 會在各自的步驟失敗（LLM 步驟記 `pending`、看門狗記 `gh_auth_failed`，[容器內的 claude 與 gh 認證（.env）](#容器內的-claude-與-gh-認證env)）。web 不讀 env file。compose 會把 env file 的值展開進 api 與 scheduler 的 `environment`，所以有真 `.env` 時：`docker compose config` 一定要加 `-q` 或 `--no-interpolate`（不加會原樣印出 token）；`docker inspect`、`docker compose run … env` 等列出容器環境變數的命令同樣會顯示 token，這些輸出都不貼到 GitHub（Issue、PR、留言與 `pr-assets`）。
- `STOCK_GIT_HEAD`：build 時寫進 image 的 commit（[scheduler 容器的排程（serve）](SCHEDULING.md#scheduler-容器的排程serve)），compose 讀不到 git，由 shell 帶入：`STOCK_GIT_HEAD="$(git rev-parse HEAD)" docker compose build`。
- `STOCK_MONITOR`、`STOCK_COORDINATION_DIR`：scheduler 的事件 monitor（`off`／`record-only`／`on`，預設 `off`）與它的佇列目錄（主機目錄，bind mount 到 `/coordination`；預設這個 checkout 的 `.coordination/`，不進 Git 與 image），見 [統籌事件 monitor](MONITOR.md)。預設值讓開發用的 `--profile scheduler` 碰不到統籌的佇列；只有正式 scheduler 設成統籌的目錄。
- `STOCK_RELEASE_TAG`：image 的 tag，預設 `latest`（`<project>-backend:latest`、`<project>-web:latest`）。[`deploy.sh`](../RELEASE.md#部署) 設成它部署的 git tag 並帶入 `STOCK_GIT_HEAD`（#340），所以正式 project 的 `docker compose ps` 顯示 `stock-lab-backend:<tag>`。對正式 project 下 `docker compose run`／`exec` 時帶同一個值（`STOCK_RELEASE_TAG=<部署的 tag>`），否則 compose 會另 build 一份 `latest`；不帶它的 `up` 會把容器換成 `latest`，看門狗以 `invariant_deploy_image` 回報（[排程看門狗](WATCHDOG.md)）。

**Windows 側**（repo 留在 Windows，使用者決定 [#1](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-6465043664)）：

- `.gitattributes` 把 `*.sh` 固定為 LF：CRLF 的腳本在容器裡跑不動。entrypoint 在 Git 裡是 100755，image 另外 `chmod 0755`。dev 的 bind mount 不保證保留執行權限位元，所以 dev 以 `sh /app/backend/docker/entrypoint.sh` 呼叫。
- 匿名 volume 蓋住 checkout 的 `.venv` 與 `frontend/node_modules`（Windows 版），容器用 image 內的依賴。依賴改了、image 重新 build 之後要 `up --renew-anon-volumes`，否則沿用舊的匿名 volume。
- WSL 2 的記憶體上限在 `%UserProfile%\.wslconfig`（`[wsl2]` 下 `memory=6GB`）。它要高於同時執行的容器上限總和：正式拓撲約 3.3 GB，dev 加 scheduler 約 4 GB。scheduler 的 2 GB 依實測：在容器內對正式 DB 副本（2.4 GB）以 `--force` 重跑一次 daily，rss 峰值約 0.95 GB（cgroup `failcnt` 0）；同一份副本由 0017 migrate 到 0020 時，`docker stats` 讀到 1.8 GiB（含 page cache）（2026-10-29，#335）。改完執行 `wsl --shutdown`，Docker Desktop 重開後生效。

### Docker Desktop 沒開

容器都跑在 Docker Desktop 的 WSL 2 VM 裡（`docker context ls` 的 `desktop-linux`，端點 `npipe:////./pipe/dockerDesktopLinuxEngine`）。重開機後還沒登入、Docker Desktop 被結束，或沒設成登入時啟動（Settings → General 的 Start Docker Desktop when you sign in），容器就都沒有在跑。

- **判讀**：`docker info --format '{{.ServerVersion}}'` 與任何 `docker compose` 命令都失敗，訊息是 `failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine; check if the path is correct and if the daemon is running: open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.`（Docker 29.9.2；2026-10-29 以不存在的 pipe 名稱重現同一格式，#341）。Docker Desktop 還在啟動時，等它顯示 Engine running 再查一次。`docker info` 有回應，但 `docker compose -p <project> ps` 沒列出 scheduler 或狀態不是 `Up`，就不是 Docker Desktop 的問題，看 `docker compose -p <project> logs scheduler`。
- **期間沒有排程，也沒有留言**：daily、news、看門狗與事件 monitor 都在 scheduler 容器內，Docker Desktop 停了就全部停；看門狗也在容器裡，所以不會在 #1 留言。主機上看得到的跡象是統籌 `patrol.sh` 印的 monitor 心跳時間不再前進（monitor 開著時，[統籌事件 monitor](MONITOR.md)）。
- **恢復**：開啟 Docker Desktop。三個服務都是 `restart: unless-stopped`，Docker Desktop 起來後容器自動回來，不必再 `up`（以 `docker compose stop`／`down` 停掉的除外）。serve 不補它啟動前錯過的時段（[scheduler 容器的排程（serve）](SCHEDULING.md#scheduler-容器的排程serve)）：錯過當天的 daily 時，看門狗在 21:30 後以 `daily_no_end` 留言，依 [重跑與回補](SCHEDULING.md#重跑與回補) 手動補跑。

## 資料庫、migration 與 readiness

程式 Alembic head 是 `0022_margin_lists`，revision chain 為 0001→0022（`app/migration_revisions.py`；0010 新增 `technical_indicators`，0011 新增排程 run 記錄表，見 [日誌與 run 記錄](SCHEDULING.md#日誌與-run-記錄)，0012 新增新聞 LLM 判讀表 `news_llm_results`，見 [NEWS_SPEC §5](../NEWS_SPEC.md#5-ai-摘要與推論)，0013 新增每日候選表 `candidate_runs`／`daily_candidates`，見 [candidate_score_v1](../spec/candidate_score.md#candidate_score_v1)，0014 新增新聞題材建議表 `theme_suggestions`／`theme_suggestion_news`，見 [新聞題材建議](../spec/theme_suggestions.md)，0015 新增候選 AI 說明表 `candidate_llm_notes`，見 [候選 AI 進出點說明](../spec/candidate_score.md#候選-ai-進出點說明)，0016 新增族群分數封存表 `group_daily_score_archive`，見 [hot_group_v1](../spec/hot_group.md)，0017 新增使用者追蹤計畫表 `tracking_plans`／`tracking_plan_sessions`，見 [使用者追蹤計畫](../spec/tracking.md#使用者追蹤計畫)，0018 新增大盤概況表 `market_summaries`，見 [大盤概況 API 契約](../DATA_SOURCES.md#大盤概況-api-契約)，0019 新增條件價位表 `strategy_levels`，見 [strategy_levels_v1](../spec/strategy_levels.md)，0020 新增官方休市表 `trading_calendar_days`，見 [DATA_SOURCES](../DATA_SOURCES.md#交易日曆)，0021 在 `chip_snapshots` 新增法人與融資各自的來源欄，見 [DATA_SOURCES](../DATA_SOURCES.md#籌碼來源)，0022 新增官方融資標的清單表 `margin_lists` 與 `signals(instrument_id, signal_date)` 的 index，見 [DATA_SOURCES](../DATA_SOURCES.md#融資標的清單)）；無法載入 Alembic 時，`init-db` 以內建步驟升級並把 revision 寫入 `schema_migrations`（`migrations.upgrade_database`）。程式 head 不代表任何 DB 已升級。策略版本的遷移規則見 [策略版本識別](../spec/README.md#策略版本識別)。連線一律用 WAL 與 30 秒 busy timeout（`app.db`）：排程的 daily 與 news 寫同一個 DB 時，短交易互相等待；daily 的寫入交易長過 30 秒時，news 遇 `database is locked` 會整個寫入單位（開 run、一個 feed、結束 run）rollback 後重做，間隔 60 秒、最多再 3 次（`news_batch.LOCK_RETRIES`），仍失敗才把該 feed 或該來源記 `failed`（[現有 worker CLI](CLI.md#現有-worker-cli)）。

readiness 只在唯讀 transaction 檢查有限 descriptor：`alembic_version` 必須恰為 current head，`schema_migrations` 必須是不重複的已知 revision 前綴（沒有 `alembic_version` 時須為完整清單）；mapped objects、必要欄名、ordered PK／FK／UNIQUE、News JSON defaults，以及 `signal_settlements` 與 `instruments` 的 identity 必須符合契約。它不執行 `quick_check`、`integrity_check`、資料 FK scan 或完整 type／CHECK／trigger／custom-schema audit，也不涵蓋 live WAL／SHM、concurrent writer、non-SQLite 與 attached schema；通過不保證任意寫入成功。

### 安全升級與復原順序

1. **備份**：解析實際 DB 絕對路徑，用 SQLite backup API 在專案外建副本；有 WAL 或未確認 writer 時不裸複製主檔。
2. **init-db**：對目標 DB 執行 `python -m worker.cli init-db`。遷移步驟只接受已知的 SQLite schema，在破壞性 DDL 前拒絕未知的 schema、constraint、index、trigger、view 或 marker 矛盾。
3. **驗證**：確認 revision 為 current head，並跑 `PRAGMA integrity_check` 與 `PRAGMA foreign_key_check`。
4. **失敗**：migration 只能前進，失敗時保留 DB 與錯誤，從備份還原到新路徑再診斷；不手動刪暫存表、補 marker、關 FK 或反覆重試。

## 容器內的 claude 與 gh 認證（.env）

容器內的 `claude -p`（news-llm、candidate_notes）與 `gh`（看門狗）不用互動登入，改讀 token（#337，使用者決定 [#1 6465043664](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-6465043664)）。token 放在跑 compose 的 checkout 根目錄的 `.env`（正式排程是發佈 checkout），由使用者手動建立；`.env` 不進 Git（`.gitignore`），compose 以 `env_file` 讀它（`STOCK_ENV_FILE`，[Docker compose](#docker-compose)）。repo 只有 [`.env.example`](../../.env.example)：key 與註解，沒有值。agent 不讀、不建、不印 `.env` 與 token。

| key | 用途與產生方式 |
| --- | --- |
| `CLAUDE_CODE_OAUTH_TOKEN` | Claude 訂閱的一年期 token。在有瀏覽器的本機跑 `claude setup-token`（走與 `/login` 相同的瀏覽器授權，印出 token，不存檔；不要在 SSH 或容器裡跑），貼進 `.env`，到期日寫在註解。只能發 model request，需 Pro／Max／Team／Enterprise。`--bare` 不讀這個變數（news-llm 不用 `--bare`）。news-llm 的子程序環境移除 `CLAUDE_CODE_*` 時保留這一個（[NEWS_SPEC §5](../NEWS_SPEC.md#5-ai-摘要與推論)）。 |
| `GH_TOKEN` | GitHub fine-grained PAT，只給 YiCheng0608/stock-lab：Issues 讀寫，Pull requests、Actions、Metadata 唯讀；到期日寫在註解。`gh` 有 `GH_TOKEN` 時優先用它、不用已存的登入。 |
| `TZ`、`STOCK_DATA_DIR` | 不用寫：compose 在容器的 `environment:` 固定 `Asia/Taipei`、`/data`（[Docker compose](#docker-compose)），env file 裡的值不生效。`.env.example` 只以註解列出。 |

不要設 `ANTHROPIC_API_KEY`／`ANTHROPIC_AUTH_TOKEN`：Claude Code 的認證優先序是 `ANTHROPIC_AUTH_TOKEN` > `ANTHROPIC_API_KEY` > apiKeyHelper > `CLAUDE_CODE_OAUTH_TOKEN` > `/login`，`-p` 下有 API key 一律使用；news-llm 與 candidate_notes 遇到就拒跑（[現有 worker CLI](CLI.md#現有-worker-cli)）。以上依官方文件 [Authentication](https://code.claude.com/docs/en/authentication)、[Errors](https://code.claude.com/docs/en/errors)、[gh environment](https://cli.github.com/manual/gh_help_environment)、[gh exit codes](https://cli.github.com/manual/gh_help_exit-codes)（2026-10-29 讀）。

- **auth error 的判定**：
  - `claude -p`：呼叫失敗時，`api_error_status` 是 401，或 stderr 與錯誤回應的 `result`（只在 `is_error` 為真時讀，否則是模型文字）有 `not logged in`、`/login`、`please log in`、`failed to authenticate`、`authentication_failed`、`oauth token`、`invalid authentication credentials`、`api error: 401` 之一（不分大小寫），就記 `not_logged_in`（`worker.news_llm.AUTH_ERROR_TEXT`）。只有數字 401 不算（例如當掉時 stack trace 的行號）。涵蓋沒有 token 也沒有登入（`Not logged in · Please run /login`），以及 token 過期或被撤銷（`Failed to authenticate. API Error: 401 OAuth token has expired`、`Failed to authenticate: OAuth token revoked …`）。`not_logged_in` 停止本次 run：送出的那一批記 `pending`，其餘批次跳過（`stopped_after_not_logged_in`），下次執行重試。
  - `gh`：exit code 4（需要認證，即沒有 token 也沒有登入），或 stderr 有 `HTTP 401`、`Bad credentials`、`gh auth login`。其他失敗（網路等）不算。
- **看門狗的留言**（[排程看門狗](WATCHDOG.md)）：
  - `llm_auth`：24 小時內 news_llm 或 candidate_notes 最近一次 run 有 `not_logged_in` 的批次。每台北日一則；之後一次 run 成功就不再留。
  - `gh_auth`：看門狗每次執行先讀一次 repo（`gh api repos/YiCheng0608/stock-lab`，`--dry-run` 不讀）。被拒時看門狗無法用 gh 留言，所以每次記 `gh_auth_failed` 到 `watchdog.log` 與 stdout（`docker logs` 看得到）；當次其他異常記 `anomaly_not_commented`，不算已留言。gh 恢復後的第一次執行在 #1 留一則（每台北日一則），寫明被拒的期間、次數與期間沒能留言的異常；仍存在的異常同一輪照常留言。gh 一直被拒時，只有日誌看得到。
- **沒有 `.env` 或 token 是空的**：compose 照常啟動（`env_file` 是 `required: false`，[Docker compose](#docker-compose)），程式照常執行，不會崩潰。`claude -p` 回 `Not logged in`，news-llm 與 candidate_notes 該批記 `pending`，run 記 `failed`，daily 與 news 的結果與結束碼不受影響（candidate_notes 見 [日誌與 run 記錄](SCHEDULING.md#日誌與-run-記錄)）；`gh` 以 exit 4 結束，看門狗記 `gh_auth_failed`。CI `compose` job 的 smoke 第 5 步（[`tools/compose/no_env_llm.sh`](../../tools/compose/no_env_llm.sh)）在沒有 env file 的 scheduler 容器裡跑真的 `claude` 與看門狗驗證這幾點。
- **換 token**：改 `.env` 後重建 scheduler 容器（`docker compose up -d --force-recreate scheduler`），容器才讀到新值。`pending` 的新聞由下一輪 news-llm 重試；`pending` 的候選說明 daily 不會重跑，以 `python -m worker.cli candidate-notes --date YYYY-MM-DD` 補（[日誌與 run 記錄](SCHEDULING.md#日誌與-run-記錄)）。
