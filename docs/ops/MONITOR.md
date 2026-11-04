<!-- owns: 統籌事件 monitor -->
# 統籌事件 monitor

`tools/ops/monitor.sh`（bash，不用 LLM）在 scheduler 容器由 serve 每分鐘跑一輪（`STOCK_MONITOR`，見本節的「scheduler 容器裡的 monitor」；切換前由工作排程器的 `\stock-lab\monitor` 常駐執行）（[#316](https://github.com/YiCheng0608/stock-lab/issues/316)；使用者同意新增，算在 #1 [6235419623](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-6235419623) 之內），替統籌輪詢 GitHub 與排程，統籌怎麼處理佇列見[統籌手冊「無人值守運作」](../COORDINATOR.md#無人值守運作)。每 60 秒（`--interval`，至少 60）一輪：

- **gh**：每輪最多 2 次，`gh pr list`（open PR 的 CI 與 `mergeStateStatus`）與 repo 層級 `issues/comments?since=`（游標存在 `logs/monitor-state.json`，第一輪往回 1 小時）；要在 #1 留言的那一輪以留言取代查留言。約 120 次／小時，帳號的 5000 次／小時由所有 session 共用。每次 gh 與 orca 呼叫最多 120 秒，逾時就當這一項失敗，照常寫心跳，不重試。已知限制：monitor 自己的 Python（`event_queue.py`）與時鐘呼叫沒有逾時，卡住時要等心跳超過 10 分鐘，由下一次排程觸發接手。
- **其他來源**：`orca worktree list`（task worktree 少於 3 個時記並行名額事件）、daily 每一個 `end` 列、news 的 news 或 news-llm 失敗的 `end` 列（各讀最新兩個日誌檔）、看門狗的 `gh_auth_failed` 列（`watchdog.log`）。
- **gh 被拒**（#338）：看門狗記 `gh_auth_failed`，或 monitor 自己的 gh 呼叫被 GitHub 拒絕（判定與看門狗相同：[`gh_auth.sh`](../../tools/ops/gh_auth.sh)，[容器內的 claude 與 gh 認證（.env）](SETUP.md#容器內的-claude-與-gh-認證env)），就記 `gh_auth` 事件，每台北日一個（`gh_auth:<台北日>`，兩個來源同一天只記一次）。這時看門狗與 monitor 都無法在 #1 留言（同一個 `GH_TOKEN`），由被喚醒的統籌用本機 gh 在 #1 留言請使用者換 token。網路錯誤不算。
- **事件**：去重後附加到 `logs/events.jsonl`（格式寫在 [`event_queue.py`](../../tools/ops/event_queue.py) 開頭）。去重鍵：PR 的 CI 結果以 PR、head commit、最新 workflow run 的 run id 與其 `required` 檢查的結論為鍵（同一 run 不重記，re-run 是新事件；被新 run 取消的舊 run 不算，最新 run 的 `required` 跑完才記）；`mergeStateStatus` 為 `CLEAN`／`DIRTY`／`BEHIND`／`UNSTABLE` 時以 PR、commit 與狀態為鍵；留言以留言 id 為鍵（編輯不重記，monitor 第一輪之前建立的留言不記）；新 PR、PR 離開 open 清單、名額以 task worktree 組合為鍵；gh 被拒以台北日為鍵。重啟後以 `events.jsonl` 去重，已記過與已標記處理（`logs/events-done.jsonl`，統籌以 `patrol.sh --done` 寫入）的事件都不會再出現。
- **喚醒**：由 waker 執行（`--waker <命令>`，以 `<命令> <terminal> <文字>` 呼叫，exit 0 已送、3 未閒置、其他為失敗；`none` 表示不喚醒、只記 `wake=deferred`，#338）。預設的 [`orca_wake.sh`](../../tools/ops/orca_wake.sh) 做法如下：有新事件時，對心跳檔（`logs/coordinator-heartbeat.json`）記的 terminal 先 `orca terminal wait --for tui-idle --timeout-ms 15000`，回 `satisfied:true` 才 `orca terminal send` 一句「有 N 個事件，請處理佇列：bash tools/ops/patrol.sh」（與派工同一規則，GUARDRAILS 規則表 #282），結果記成 `events.jsonl` 的 `wake` 列；同一事件只在第一次成功送出時喚醒。沒等到閒置（`not_idle`，terminal 不存在或 wait 逾時也算）或送出失敗（沒有心跳、Orca 拒收）每 10 分鐘再試。已知限制：權限詢問畫面也會讓 `tui-idle` 回 `satisfied:true`（#315 實測），這時送出的文字仍可能落在那個畫面上。
- **請開統籌**：佇列有事件已 60 分鐘、期間統籌心跳都沒更新時，在 #1 留言「待使用者：請開統籌」，同一心跳只留一則（`stale` 列）；不開 session。
- **自身狀態**：每輪寫 `logs/monitor-heartbeat.json`、把 daily／news 最新日誌的 `end` 列與 `watchdog.log` 最後一列記進 `logs/monitor-state.json`（`patrol.sh` 印這份，不自己讀日誌，#338），並在 `logs/monitor.log` 記一列（UTC 時間、`poll`、`gh_calls`、新事件與未處理數、喚醒結果）；心跳另記 gh 連續失敗的輪數、從何時起與最後的錯誤（失敗那次呼叫自己的 stderr 最後一行；逾時記 `timeout`；沒有輸出記 `exit <碼>`；`patrol.sh` 也印出）。看門狗在心跳超過 10 分鐘或 gh 連續失敗 10 輪時留言（[排程看門狗](WATCHDOG.md)）。同時只跑一個（`logs/monitor.lock/`，內容是持有者的 pid、token 與主機名稱；同一主機時 pid 已不在或心跳超過 10 分鐘就視為殘留接手；鎖是別的主機或容器的（另一個 PID namespace，pid 無從判斷）時，心跳超過 3 分鐘才接手，#338）。每輪開頭、在 #1 留言前與寫佇列前都檢查鎖：被接手的舊 monitor 一發現鎖已不是自己的，就記 `lock_lost` 結束，不再呼叫 gh、留言或寫佇列，也不刪新持有者的鎖與工作目錄（各 monitor 的工作目錄是 `monitor.lock/work.<pid>`）。

`--record-only` 只記事件，不喚醒也不留言（gh 照樣讀），用來在註冊前以真的 GitHub 驗證。執行環境：Git Bash、PATH 上有已登入的 `gh`、Orca CLI（排程的 PATH 沒有 orca，註冊時寫入 `orca.exe` 完整路徑）。以下是工作排程器（切換前）的命令，在發佈 checkout 執行：

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

**scheduler 容器裡的 monitor**（#338）：`worker.cli serve` 在 `STOCK_MONITOR` 為 `on`（或 `record-only`）時每分鐘跑一次 `monitor.sh --once`（[scheduler 容器的排程（serve）](SCHEDULING.md#scheduler-容器的排程serve)），每一輪都是新啟動的 monitor，所以「重啟後不重複喚醒」就是每一輪的常態；兩輪間隔由觸發保證（每分鐘一次）。檔案分兩處：

| 位置 | 檔案 | 寫入者 |
| --- | --- | --- |
| 佇列目錄：主機的 `STOCK_COORDINATION_DIR`，容器內 `/coordination`（`--queue-dir`） | `events.jsonl`、`monitor-state.json`、`monitor-heartbeat.json`、`monitor.log`、`monitor.lock/`、`monitor.stop` | 容器內的 monitor |
| 同上 | `coordinator-heartbeat.json`、`events-done.jsonl`、`compactions/`、`handoff-*.json` | 主機上的 `patrol.sh`、`compact_hook.sh` 與統籌 |
| volume `stock-data` 的 `/data/logs` | daily、news、看門狗的日誌 | 各 job |

compose 的預設佇列目錄是 checkout 內的 `.coordination/`，任務 worktree 以 `--profile scheduler` 起的 scheduler 不會寫進正式佇列，也不會跟正式 monitor 搶鎖。正式 scheduler（發佈 checkout）要設兩個值，放在發佈 checkout 根目錄的 `.env`（compose 以它展開變數，[Docker compose](SETUP.md#docker-compose)）；[`deploy.sh`](../RELEASE.md#部署) 不帶呼叫它的 shell 裡的這兩個值，免得殘留的沙盒設定把正式佇列指走：

| 變數 | 正式值 |
| --- | --- |
| `STOCK_MONITOR` | `on`（只記事件、不喚醒也不留言時用 `record-only`） |
| `STOCK_COORDINATION_DIR` | 統籌的資料目錄的 `logs/`（[LOCAL](LOCAL.md#正式位置使用者決定)） |

所以 `patrol.sh`、`compact_hook.sh` 與[統籌手冊](../COORDINATOR.md#無人值守運作)的路徑都不變，每個檔仍只有一個寫入者；job 日誌在 volume 裡，`patrol.sh` 印的是 monitor 寫進 `monitor-state.json` 的最後一列。看門狗以 `--monitor-dir /coordination` 讀 monitor 的心跳。停止：`monitor.stop` 對每分鐘一輪的 monitor 沒有作用，改把 `STOCK_MONITOR` 設成 `off` 後 `docker compose up -d scheduler`。

**wake listener**（#338，使用者選的做法 B3）：容器裡沒有 Orca，喚醒與 task worktree 數經主機上常駐的 [`wake_listener.py`](../../tools/ops/wake_listener.py)。serve 的 `--monitor-waker` 預設 [`http_wake.sh`](../../tools/ops/http_wake.sh)、`--monitor-orca` 預設 [`http_orca.sh`](../../tools/ops/http_orca.sh)（只答 `worktree list --json`），兩者都以 `STOCK_WAKE_TOKEN` 呼叫 `STOCK_WAKE_URL`（預設 `http://host.docker.internal:47338/wake`）。

- **只綁 `127.0.0.1:47338`，而且獨占**：Docker Desktop 把容器對 `host.docker.internal` 的連線代理到主機的 localhost（2026-10-29 實測，listener 看到的來源一律是 `127.0.0.1`），所以不用綁 `0.0.0.0`、不用開防火牆，LAN 連不到；代價是本機任何程序與任何容器都連得到，靠下面的 token、固定模板與限流把關。listener 不設 `SO_REUSEADDR`，Windows 另設 `SO_EXCLUSIVEADDRUSE`：port 已被別的程序（或另一個 listener）占用時，listener 自己就綁不到而結束（`127.0.0.1:47338 綁不到`），不會跟它共用。
- **請求**：只收 `POST /wake` 與 `POST /worktrees`，都要 `Authorization: Bearer <token>`；不帶或錯的在任何 60 秒內前 10 次回 401 並各記一列 `refused reason=token`，之後回 429、不逐列記，被擋的次數記在下一次 401 那一列（`held_back=N`）。其他方法 405、其他路徑 404；`Content-Length` 不是非負整數（負數、非數字）400，超過 1 KB 413；body 的內容一律不讀。
- **送進 terminal 的只有固定模板**：terminal 取自主機的 `coordinator-heartbeat.json`，handle 只接受英數、`_`、`-` 而且不以 `-` 開頭（`event_queue.HANDLE`；以 `-` 開頭的會被 orca 當成選項，例如 `--enter`），不合就視為沒有心跳、回 `no_heartbeat`；傳給 orca 時寫成 `--terminal=<handle>`。N 由 listener 讀佇列算，文字是「有 N 個事件，請處理佇列：bash tools/ops/patrol.sh（處理完以 --done 標記）」。送出照 `orca_wake.sh`：`tui-idle` 回 `satisfied:true` 才送。orca 對已結束的 terminal 也回 `satisfied:true`，接著 send 失敗，記 `send_failed`，不算已送。
- **信任邊界**（#338 review）：容器寫得到 bind mount 裡的檔，包括統籌的 `coordinator-heartbeat.json`，所以容器（或拿到容器權限的人）能決定 listener 把固定模板送進哪個 terminal。可以接受，因為能送的只有上面那一句固定文字（呼叫端的任何內容都不會送出，N 是整數），而且只送進 orca 判定為閒置的 Orca terminal：最壞是某個閒置的 agent 收到「請處理佇列：bash tools/ops/patrol.sh」，不會被帶去執行別的指令。容器本來就持有 `GH_TOKEN` 等憑證，這不是新增的權限。
- **`/worktrees`**：本機 `orca worktree list --json` 裡 `refs/heads/task/` 的 branch，包成 Orca 的 envelope；orca 失敗回 502，monitor 那一輪記 `worktrees=failed`、不記名額事件，不當成名額已空。
- **限流**：每種請求同時只處理一個，上次回答後 30 秒內再來回 429 `throttled`；被拒的請求另有上面每分鐘 10 次的限制。
- **回答與 exit code**：`/wake` 回 `sent`、`not_idle`、`send_failed`、`no_heartbeat`、`nothing_pending`；`http_wake.sh` 對 `sent` exit 0、`not_idle` exit 3，其他（含 listener 沒在跑、401、429）exit 1，monitor 記失敗的喚醒，10 分鐘後再試，事件留在佇列。每個請求在主機 `<資料目錄>/logs/wake-listener.log` 記一列。
- **token**：`STOCK_WAKE_TOKEN` 只寫在發佈 checkout 根目錄那份由使用者自己建立的認證檔（`.env`，[容器內的 claude 與 gh 認證（.env）](SETUP.md#容器內的-claude-與-gh-認證env)），至少 32 字元、不含空白；容器經 `env_file` 拿到它，listener 以 `--token-file` 讀同一個檔、只取這一列。由使用者產生並寫入（例如 `python -c "import secrets; print(secrets.token_urlsafe(32))"`），agent 不產生、不讀；換 token 後重建 scheduler 容器，並結束 listener 後重跑 `wake_listener_start.sh`。

**啟動**（使用者決定，#338）：listener 只負責喚醒統籌，所以由統籌 session 啟動，不在 Windows 另外安裝。統籌接手時、每次處理佇列時跑 `bash tools/ops/wake_listener_start.sh`（[`wake_listener_start.sh`](../../tools/ops/wake_listener_start.sh)），可重複執行：

- 先 `GET /health`（不需 token，只回 `{"result": "ok", "service": "stock-lab-wake"}`）：有回應就 exit 0、不另起；port 沒有人聽才在背景啟動並等到 `/health` 回應，印出停止它的命令 `Stop-Process -Id (Get-NetTCPConnection -LocalPort 47338 -State Listen).OwningProcess`（不印 pid：Git Bash 的 pid 不是 Windows 的，拿去 `Stop-Process` 會停錯程序）；port 被別的程序占用（回應不是 listener 的）就 exit 2 並印出查占用者的命令；起不來（例如認證檔沒有 `STOCK_WAKE_TOKEN`）exit 1 並印出原因。`--status` 只回報、不啟動，`patrol.sh` 每次都印這一列。
- 認證檔的路徑（發佈 checkout 根目錄那份）寫在腳本裡，不出現在統籌的命令裡（命令提到它會被 agent hook 擋下）；listener 的輸出附加到 `<資料目錄>/logs/wake-listener.out`。
- **生命週期**：listener 在啟動它的 Bash 指令結束後繼續執行，但跟著啟動它的統籌 terminal 結束（Orca 關 terminal 時結束它底下所有程序，PowerShell 的 `Start-Process` 也一樣，2026-10-29 實測）。
  - 換手時新統籌接手先跑腳本：舊統籌的 listener 還在就沿用，它每次喚醒前都重讀心跳檔，喚醒的是新統籌；收尾關掉舊 terminal 後舊 listener 跟著結束，所以新統籌關掉舊 terminal 後再跑一次腳本（[統籌手冊](../COORDINATOR.md#統籌-session)）。
  - 統籌 session 結束而沒有接手者時 listener 也結束：沒有統籌就沒有喚醒對象，monitor 記 `send_failed`、事件留在佇列，佇列等 60 分鐘後照常在 #1 留「請開統籌」。listener 留著（例如 terminal 還開著）也不會出錯：心跳指向已結束的 terminal 時 send 失敗，記 `send_failed`。
