<!-- owns: 排程註冊與管理 -->
# Windows 工作排程器（已停用，不再當回退）

正式排程只有 scheduler 容器的 `worker.cli serve`（[排程](../SCHEDULING.md)）。Windows 工作排程器在 Docker 切換（#342，2026-11-03）後停用，**不再當回退**（#677）：本文只記它的註冊方式與現況。其他文件提到工作排程器（切換前）的做法時，只留一句連到本文。

**工作排程器的現況**（2026-11-14 以 `Get-ScheduledTask -TaskPath \stock-lab\` 讀回）：`daily`、`news`、`watchdog` 三個工作都是 `Disabled`，最後一次執行在 2026-11-02～03。它們的動作指向發佈 checkout 的 `.venv` 並帶 `-GitPull`；發佈 checkout 現在停在 `deploy.sh` 部署的 tag，含 #333（job 只在 Linux 執行），工作一啟用就會以 exit 69 結束，所以**不要啟用**。要不要從主機移除這些工作與 `tools/*.ps1`、`tools/ops/Register-*.ps1`，由使用者決定後另開 Issue。資料在 volume `stock-data`；主機資料目錄的 `stock.db` 與 `raw/` 已於 2026-11-05 刪除（[LOCAL](../LOCAL.md#正式位置使用者決定)）。

**為什麼不能回退**（#677 AC-1，[查證](https://github.com/YiCheng0608/stock-lab/issues/677#issuecomment-6862287753)）：切換時的回退腳本 `tools/ops/cutover.sh rollback` 會把發佈 checkout 切回 `pre-docker`（`0f99fea`，alembic head `0022_margin_lists`）並啟用工作；正式 DB 之後已升到 `0031` 以上，舊程式的 `init_db` 對它是 `Can't locate revision`，主機也已沒有切換前的 DB。腳本與它的文件已刪除，歷史版本見 [`ac08b1bb` 的本文「Docker 切換與回退（cutover.sh）」](https://github.com/YiCheng0608/stock-lab/blob/ac08b1bb786fa52fae3ef8334abbe75cb5930b89/docs/ops/platform/windows.md#docker-切換與回退cutoversh)與 [`tools/ops/cutover.sh`](https://github.com/YiCheng0608/stock-lab/blob/ac08b1bb786fa52fae3ef8334abbe75cb5930b89/tools/ops/cutover.sh)；它只適用 schema 不超過 `0022` 的 DB。

## daily／news 工作的註冊與管理

三個位置（使用者 2026-10-17 決定，見[排程](../SCHEDULING.md)開頭與[本機路徑](../LOCAL.md#正式位置使用者決定)）：

| 位置 | 路徑 | 說明 |
| --- | --- | --- |
| 資料目錄 | 正式資料目錄（[LOCAL](../LOCAL.md#正式位置使用者決定)）；scheduler 容器是 volume `stock-data` 的 `/data` | 正式 `stock.db`、`raw/`、`logs/`，與 job 的鎖 `locks/`。排程以 `--data-dir`（serve 傳 `/data`；工作排程器的註冊參數 `-DataDir`）傳入並設成 worker 子程序的 `STOCK_DATA_DIR`（預設依序為 `STOCK_DATA_DIR`、`~/stock-lab-data`），不由 cwd 推導。 |
| 發佈 checkout | 發佈 checkout（[LOCAL](../LOCAL.md#正式位置使用者決定)） | repo 的獨立 clone，停在部署的 tag（detached HEAD）；排程起跑不 `git pull`，master 合併的改動要打 tag、部署後才進排程。Docker 切換（#342）後它是正式 compose project 的目錄，只由 `tools/ops/deploy.sh <tag>` 改變：checkout tag、build 打 tag 的 image、`compose up -d`，部署記錄在 volume 的 `/data/logs/deploy.json`（[RELEASE](../../RELEASE.md#部署)，#340）。排程**只**從這裡執行，不從 `master` 管理 checkout 或任務 worktree。V1 G7 窗口期間（已結束）的 `release/v1` 隔離見 [RELEASE 的 V1 發佈隔離（歷史）](../../RELEASE.md#v1-發佈隔離歷史)。 |
| Python | 發佈 checkout 的 venv（[LOCAL](../LOCAL.md#正式位置使用者決定)） | 工作排程器用：依 checkout 的 `backend/requirements.txt` 與 `backend/validation-requirements.lock.txt` 安裝。預設依序為 `-PythonPath`（別名 `-Python`）、`STOCK_PYTHON`、發佈 checkout 的 `.venv`。scheduler 容器用 image 內的依賴，`deploy.sh` 不碰 venv（#340）。 |

**scheduler 容器**：觸發與命令見 [scheduler 容器的排程（serve）](../SCHEDULING.md#scheduler-容器的排程serve)，部署見 [RELEASE](../../RELEASE.md#部署)。不經排程執行一次：`STOCK_RELEASE_TAG=<部署的 tag> docker compose -p <正式 project> exec scheduler python -m worker.cli job daily --trigger manual [--date YYYY-MM-DD] [--force]`（`--data-dir` 預設 compose 固定的 `STOCK_DATA_DIR=/data`，`--min-free-memory-gb` 預設 2，`claude` 用 image 的 PATH；news 同上換成 `job news`，另可加 `--skip-news-llm`，`--date` 只標記 run 日期）。停用與恢復見 [重跑與回補](../SCHEDULING.md#重跑與回補) 的 `stop scheduler`；回補、回測起跑時自己開[維護模式](../SCHEDULING.md#維護模式)，維護模式中這裡的手動 `job` 也只記 skipped，要跑就直接 `worker.cli daily`。

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
| 不經排程執行一次 | 在 `backend` 目錄 `<py> -m worker.cli job daily --data-dir <data> --trigger manual [--date YYYY-MM-DD] [--force] [--claude-cli <claude.exe>]`（`--min-free-memory-gb` 預設 2）；news 另可加 `--claude-cli <claude.exe>`、`--skip-news-llm`，`--date` 只給 news（news-llm 的 `--date` 是篩選，不帶）。`tools/Invoke-WorkerJob.ps1` 只把舊參數（`-Job`、`-GitPull`、`-MinFreeMemoryGB`…）轉成這條命令，留給 #313 前註冊、還沒重新註冊的工作 |
| news 的 news-llm | 註冊 news 時指定 `-ClaudeCli <原生 claude.exe>`；未給時依序取 `STOCK_CLAUDE_CLI`、PATH 上第一個 `claude.exe`，都沒有或是 `.cmd` shim 就拒絕註冊。停用：同一條註冊命令改加 `-NoNewsLlm`（工作內為 `--skip-news-llm`）；恢復：去掉 `-NoNewsLlm` 再註冊一次。 |
| daily 的 candidate_notes | 註冊 daily 時加 `-ClaudeCli <原生 claude.exe>`（只認明確參數，不查 `STOCK_CLAUDE_CLI` 或 PATH；不存在或不是 `.exe` 就拒絕註冊），工作內以 `--claude-cli` 交給 job、再以 `STOCK_CLAUDE_CLI` 傳給 worker。未加時照常註冊，`Claude:` 列顯示 `(not set; …)`，該步驟依序用工作環境的 `STOCK_CLAUDE_CLI`、PATH 上的 `claude`，都找不到或找到的不是 `.exe` 就記 `cli_not_found`、不呼叫，daily 結果不受影響。 |

| 工作 | 觸發 | 動作 |
| --- | --- | --- |
| `\stock-lab\daily` | 週一至週五台北 18:30，21:30 再跑一次（`-TaipeiTimes` 可改） | `<py 同目錄的 pythonw.exe> -m worker.cli job daily --trigger scheduler --data-dir <data> --log-dir <data>/logs --min-free-memory-gb 2 [--claude-cli <claude.exe>]`（註冊參數 `-DailyMinFreeMemoryGB`、`-ClaudeCli`），單次上限 2.5 小時 |
| `\stock-lab\news` | 每天每 2 小時（`-IntervalHours`），從下一個整點區間開始 | 同上換成 `job news`、`--min-free-memory-gb 1`、`--claude-cli <claude.exe>`（註冊參數 `-NewsMinFreeMemoryGB`；`-NoNewsLlm` 時改為 `--skip-news-llm`）：先 `news`、再 `news-llm`，兩者合計單次上限 90 分鐘 |

工作排程器的兩個工作都以目前使用者、互動式登入、一般權限執行，不存密碼，使用者登入時才跑；錯過的時段在登入後補跑（StartWhenAvailable）。工作執行 `pythonw.exe`（沒有主控台視窗；venv 沒有時用 `python.exe`），job 再以 `python.exe` 無視窗啟動 worker。單一執行個體與單次上限由 job 保證（[日誌與 run 記錄](../SCHEDULING.md#日誌與-run-記錄)）；工作排程器另設「前一次未結束不另起」與比 job 上限多 10 分鐘的上限，當第二道防線。主機不在台灣時區時腳本自動換算本機時間。工作排程器的 PATH 與互動 shell 不同，所以 news-llm 與 candidate_notes 要在註冊時以 `-ClaudeCli` 寫入原生 `claude.exe` 的完整路徑（上表）。回補、回測期間以 `Disable-ScheduledTask` 停用 daily，完成後再啟用（scheduler 容器改由作業自己開[維護模式](../SCHEDULING.md#維護模式)）；只停 news-llm 用 `-NoNewsLlm` 重新註冊 news，整個 news 停用用 `Disable-ScheduledTask`。

休市日不寫進觸發：週間無交易日時官方來源回 no-data。當日目標第一次兩市都回 no-data（通常是 18:30）記 `non_trading_unconfirmed`，不算完成；21:30 再問一次仍是 no-data 才記 `non_trading_day`，這次有行情就照常跑完。目標日早於今日（手動補跑過去日期）時一次 no-data 即記 `non_trading_day`。三大法人與融資公布時間晚於收盤且不固定，18:30 若因缺這些資料而 collect 為 `partial`，analyze 不會執行，由 21:30 補齊；當日已 `success` 後的 21:30 記一列 `skipped`（`already_complete`），只再抓一次當日的兩份三大法人檔（[重跑與回補的冪等](../SCHEDULING.md#重跑與回補)），日線、融資、事件不再請求；已 `non_trading_day` 的日期什麼都不抓。

**單一執行個體與起跑前檢查**（job）：同一資料目錄的同種 job 以 `<data>/locks/<job>.lock` 的檔案鎖（`fcntl`）一次只跑一個，鎖由作業系統在 job 結束時釋放，被強制終止也不殘留；拿不到鎖記 `already_running`（daily 只在 DB 已是程式 head 時於 `schedule_runs` 留列；不是 head 時持鎖的 daily 可能正在 migrate，migration 在同一個交易裡先讀數分鐘再寫，期間別的連線寫入一列就會讓它失敗，所以只記日誌與 JSON 結果的 `error`）。拿到鎖後：可用實體記憶體（`/proc/meminfo` 的 `MemAvailable`，不用 WMI，#246）低於 `--min-free-memory-gb`（直接執行時預設 2；註冊時 daily 2、news 1）記 `low_memory`；這個 checkout 有 `index.lock` 或 `MERGE_HEAD` 記 `git_busy`（image 不含 `.git`，scheduler 容器裡不會發生）。這些都不執行 worker，等下一次觸發；daily 另在 `schedule_runs` 留一列 `skipped` 與原因，news 只寫日誌。全市場 analyze＋evaluate＋candidates＋indicators 峰值約 0.3 GB（[限制](../SCHEDULING.md#限制)），daily 門檻 2 GB 保留 collect 與其他程式的餘裕；2026-10-18 前註冊的工作仍是 6，要在發佈 checkout 重跑「註冊或更新」才生效。

**執行的版本**（#314、#340）：job 不更新程式，程式是 [`deploy.sh`](../../RELEASE.md#部署) 部署的 image。版本只有一套：image 的 `STOCK_IMAGE_TAG`（例如 `stock-lab-backend:v1.1.0`）與 `STOCK_GIT_HEAD`（該 tag 的 commit）。job 把兩者寫進日誌（`--- version image=<…> head=<…>`，沒有時 `unknown`），daily 記在 run 列的 `summary_json.runtime`（[日誌與 run 記錄](../SCHEDULING.md#日誌與-run-記錄)）；job 不執行 git。#314 前註冊的工作仍帶 `--git-pull`，job 照收、不 pull，日誌記一列 `--- --git-pull ignored`；重跑「註冊或更新」後就不再帶。

## 看門狗與事件 monitor 的工作

正式的看門狗與事件 monitor 由 scheduler 容器的 serve 執行（[排程看門狗](../WATCHDOG.md)、[統籌事件 monitor](../MONITOR.md)），判定、日誌與鎖兩邊相同；以下是工作排程器的版本（切換前），已停用。

### 事件 monitor（`\stock-lab\monitor`）

切換前 monitor 由工作排程器的 `\stock-lab\monitor` 常駐執行（#316）。`--record-only` 用來在註冊前以真的 GitHub 驗證。執行環境：Git Bash、PATH 上有已登入的 `gh`、Orca CLI（排程的 PATH 沒有 orca，註冊時寫入 `orca.exe` 完整路徑）。以下命令在發佈 checkout 執行：

| 動作 | 命令 |
| --- | --- |
| 預覽 | `powershell -ExecutionPolicy Bypass -File tools/ops/Register-Monitor.ps1 -WhatIf` |
| 註冊或更新 | `powershell -ExecutionPolicy Bypass -File tools/ops/Register-Monitor.ps1`（`-DataDir`、`-PythonPath`、`-OrcaPath` 預設 `STOCK_DATA_DIR`、`.venv`、`%LOCALAPPDATA%\Programs\orca\resources\bin\orca.exe`；`-RecordOnly` 註冊只記事件的版本） |
| 查詢 | `schtasks /query /tn "\stock-lab\monitor" /v /fo list`；`tail logs/monitor.log` |
| 停止 | 建立 `<資料目錄>/logs/monitor.stop`：monitor 做完這一輪就刪掉它並結束（停工作排程可能只結束承載 bash 的 PowerShell）；要停久一點先 `Disable-ScheduledTask -TaskPath \stock-lab\ -TaskName monitor` |
| 移除 | `powershell -ExecutionPolicy Bypass -File tools/ops/Register-Monitor.ps1 -Unregister`（同時建立 `monitor.stop`） |
| 手動一輪 | `bash tools/ops/monitor.sh --once --record-only` |

工作以目前使用者、Interactive logon、隱藏執行，登入時啟動，之後每 5 分鐘再觸發一次：執行中就忽略（`IgnoreNew`），已結束就重新啟動，所以 monitor 掛掉最多停 5 分鐘；沒有執行時限。啟動時留著的 `monitor.stop` 屬於先前的 monitor，會刪掉並記 `stop_file_removed`。

上線（第一次以喚醒模式註冊，或從 `-RecordOnly` 改成喚醒模式）：佇列裡已有的事件都還沒喚醒過，註冊後第一輪會一次喚醒全部；放了 60 分鐘以上的事件，如果統籌心跳比它們舊，還會馬上在 #1 留「請開統籌」。所以註冊前先做以下其中一項：

1. 統籌跑 `bash tools/ops/patrol.sh --done <最後 seq>`，把既有事件都標成已處理（最後 seq 是 `patrol.sh` 印的「未處理事件」範圍的最大值）。
2. 用沒有 `events.jsonl` 的全新資料目錄（`-DataDir`）。

之後再執行「註冊或更新」，並以 `tail logs/monitor.log` 確認第一輪是 `new=0`，或喚醒的只有新事件。

### 看門狗（`\stock-lab\watchdog`）

切換前看門狗是工作排程器的 `\stock-lab\watchdog`，每 15 分鐘執行。以下命令在發佈 checkout 執行：

| 動作 | 命令 |
| --- | --- |
| 預覽 | `powershell -ExecutionPolicy Bypass -File tools/ops/Register-Watchdog.ps1 -WhatIf` |
| 註冊或更新 | `powershell -ExecutionPolicy Bypass -File tools/ops/Register-Watchdog.ps1`（`-DataDir`、`-PythonPath` 預設 `STOCK_DATA_DIR`、`.venv`；`-DryRun` 註冊只判定不留言的版本，用來以 `Start-ScheduledTask -TaskPath \stock-lab\ -TaskName watchdog` 驗證排程環境） |
| 查詢 | `schtasks /query /tn "\stock-lab\watchdog" /v /fo list` |
| 停用／啟用 | `Disable-ScheduledTask -TaskPath \stock-lab\ -TaskName watchdog`／`Enable-ScheduledTask ...` |
| 移除 | `powershell -ExecutionPolicy Bypass -File tools/ops/Register-Watchdog.ps1 -Unregister` |
| 手動判定 | `bash tools/ops/watchdog.sh --dry-run` |
| 手動核對某交易日 | `python tools/ops/watchdog_helper.py data-check <stock.db> <YYYY-MM-DD> [--offline] [--all]`（唯讀，不記日誌、不留言） |

工作以目前使用者、Interactive logon、隱藏執行，登入時才跑，同時只跑一個（`IgnoreNew`），10 分鐘逾時；找不到 Python、不取鎖的那一輪由工作的「前一次未結束不另起」擋重疊。腳本路徑寫在工作參數裡，腳本改名或搬移後要在發佈 checkout 重跑「註冊或更新」。
