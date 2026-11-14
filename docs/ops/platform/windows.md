<!-- owns: 排程註冊與管理 -->
# Windows 工作排程器（已停用，不再當回退）

正式排程只有 scheduler 容器的 `worker.cli serve`（[排程](../SCHEDULING.md)）。Windows 工作排程器在 Docker 切換（#342，2026-11-03）後停用，**不再當回退**（#677）：本文只記它當時的做法與現況。其他文件提到工作排程器（切換前）的做法時，只留一句連到本文。

**工作排程器的現況**：使用者 2026-11-14 同意清掉後，統籌移除了 `\stock-lab\` 的 `daily`、`news`、`watchdog` 三個停用工作（[#1 6869576064](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-6869576064)），`Get-ScheduledTask` 讀回已沒有任何工作引用本 repo（[#683 AC-1](https://github.com/YiCheng0608/stock-lab/issues/683#issuecomment-6870652391)）。註冊用的 `tools/Invoke-WorkerJob.ps1`、`tools/Register-WorkerSchedule.ps1`、`tools/ops/Register-Monitor.ps1`、`tools/ops/Register-Watchdog.ps1` 已刪除（#683），repo 不再有任何 Windows 腳本（`checks.py repository` 檢查，[GUARDRAILS](../../GUARDRAILS.md)）；刪除前的版本與它們的命令見 [`7cca809c` 的本文](https://github.com/YiCheng0608/stock-lab/blob/7cca809c18ae1cdab635bd06d565a7008e72760f/docs/ops/platform/windows.md)與 [`tools/`](https://github.com/YiCheng0608/stock-lab/tree/7cca809c18ae1cdab635bd06d565a7008e72760f/tools)。發佈 checkout 的 `.venv` 未動（另議）。資料在 volume `stock-data`；主機資料目錄的 `stock.db` 與 `raw/` 已於 2026-11-05 刪除（[LOCAL](../LOCAL.md#正式位置使用者決定)）。

**為什麼不能回退**（#677 AC-1，[查證](https://github.com/YiCheng0608/stock-lab/issues/677#issuecomment-6862287753)）：切換時的回退腳本 `tools/ops/cutover.sh rollback` 會把發佈 checkout 切回 `pre-docker`（`0f99fea`，alembic head `0022_margin_lists`）並啟用工作；正式 DB 之後已升到 `0031` 以上，舊程式的 `init_db` 對它是 `Can't locate revision`，主機也已沒有切換前的 DB。腳本與它的文件已刪除，歷史版本見 [`ac08b1bb` 的本文「Docker 切換與回退（cutover.sh）」](https://github.com/YiCheng0608/stock-lab/blob/ac08b1bb786fa52fae3ef8334abbe75cb5930b89/docs/ops/platform/windows.md#docker-切換與回退cutoversh)與 [`tools/ops/cutover.sh`](https://github.com/YiCheng0608/stock-lab/blob/ac08b1bb786fa52fae3ef8334abbe75cb5930b89/tools/ops/cutover.sh)；它只適用 schema 不超過 `0022` 的 DB。

## daily／news 工作的註冊與管理

三個位置（使用者 2026-10-17 決定，見[排程](../SCHEDULING.md)開頭與[本機路徑](../LOCAL.md#正式位置使用者決定)）：

| 位置 | 路徑 | 說明 |
| --- | --- | --- |
| 資料目錄 | 正式資料目錄（[LOCAL](../LOCAL.md#正式位置使用者決定)）；scheduler 容器是 volume `stock-data` 的 `/data` | 正式 `stock.db`、`raw/`、`logs/`，與 job 的鎖 `locks/`。排程以 `--data-dir`（serve 傳 `/data`）傳入並設成 worker 子程序的 `STOCK_DATA_DIR`（預設依序為 `STOCK_DATA_DIR`、`~/stock-lab-data`），不由 cwd 推導。 |
| 發佈 checkout | 發佈 checkout（[LOCAL](../LOCAL.md#正式位置使用者決定)） | repo 的獨立 clone，停在部署的 tag（detached HEAD）；排程起跑不 `git pull`，master 合併的改動要打 tag、部署後才進排程。Docker 切換（#342）後它是正式 compose project 的目錄，只由 `tools/ops/deploy.sh <tag>` 改變：checkout tag、build 打 tag 的 image、`compose up -d`，部署記錄在 volume 的 `/data/logs/deploy.json`（[RELEASE](../../RELEASE.md#部署)，#340）。排程**只**從這裡執行，不從 `master` 管理 checkout 或任務 worktree。V1 G7 窗口期間（已結束）的 `release/v1` 隔離見 [RELEASE 的 V1 發佈隔離（歷史）](../../RELEASE.md#v1-發佈隔離歷史)。 |
| Python | 發佈 checkout 的 venv（[LOCAL](../LOCAL.md#正式位置使用者決定)） | 工作排程器用過（依 checkout 的 `backend/requirements.txt` 與 `backend/validation-requirements.lock.txt` 安裝），工作移除後未刪（另議）。scheduler 容器用 image 內的依賴，`deploy.sh` 不碰 venv（#340）。 |

**scheduler 容器**：觸發與命令見 [scheduler 容器的排程（serve）](../SCHEDULING.md#scheduler-容器的排程serve)，部署見 [RELEASE](../../RELEASE.md#部署)。不經排程執行一次：`STOCK_RELEASE_TAG=<部署的 tag> docker compose -p <正式 project> exec scheduler python -m worker.cli job daily --trigger manual [--date YYYY-MM-DD] [--force]`（`--data-dir` 預設 compose 固定的 `STOCK_DATA_DIR=/data`，`--min-free-memory-gb` 預設 2，`claude` 用 image 的 PATH；news 同上換成 `job news`，另可加 `--skip-news-llm`，`--date` 只標記 run 日期）。停用與恢復見 [重跑與回補](../SCHEDULING.md#重跑與回補) 的 `stop scheduler`；回補、回測起跑時自己開[維護模式](../SCHEDULING.md#維護模式)，維護模式中這裡的手動 `job` 也只記 skipped，要跑就直接 `worker.cli daily`。

**工作排程器（切換前，工作已移除）**：發佈 checkout 以 `tools/Register-WorkerSchedule.ps1` 註冊 `\stock-lab\daily`（週一至週五台北 18:30 與 21:30）與 `\stock-lab\news`（每 2 小時），工作以目前使用者、互動式登入執行發佈 checkout `.venv` 的 `pythonw.exe -m worker.cli job daily|news --trigger scheduler`（daily `--min-free-memory-gb 2`、news `1`；news-llm 與 candidate_notes 以 `-ClaudeCli` 寫入原生 `claude.exe` 的完整路徑，因為工作排程器的 PATH 與互動 shell 不同）。註冊、查詢、停用與移除的命令見刪除前的版本（本文開頭的連結）。

休市日不寫進觸發：週間無交易日時官方來源回 no-data。當日目標第一次兩市都回 no-data（通常是 18:30）記 `non_trading_unconfirmed`，不算完成；21:30 再問一次仍是 no-data 才記 `non_trading_day`，這次有行情就照常跑完。目標日早於今日（手動補跑過去日期）時一次 no-data 即記 `non_trading_day`。三大法人與融資公布時間晚於收盤且不固定，18:30 若因缺這些資料而 collect 為 `partial`，analyze 不會執行，由 21:30 補齊；當日已 `success` 後的 21:30 記一列 `skipped`（`already_complete`），只再抓一次當日的兩份三大法人檔（[重跑與回補的冪等](../SCHEDULING.md#重跑與回補)），日線、融資、事件不再請求；已 `non_trading_day` 的日期什麼都不抓。

**單一執行個體與起跑前檢查**（job）：同一資料目錄的同種 job 以 `<data>/locks/<job>.lock` 的檔案鎖（`fcntl`）一次只跑一個，鎖由作業系統在 job 結束時釋放，被強制終止也不殘留；拿不到鎖記 `already_running`（daily 只在 DB 已是程式 head 時於 `schedule_runs` 留列；不是 head 時持鎖的 daily 可能正在 migrate，migration 在同一個交易裡先讀數分鐘再寫，期間別的連線寫入一列就會讓它失敗，所以只記日誌與 JSON 結果的 `error`）。拿到鎖後：可用實體記憶體（`/proc/meminfo` 的 `MemAvailable`，不用 WMI，#246）低於 `--min-free-memory-gb`（直接執行時預設 2；排程 daily 2、news 1）記 `low_memory`；這個 checkout 有 `index.lock` 或 `MERGE_HEAD` 記 `git_busy`（image 不含 `.git`，scheduler 容器裡不會發生）。這些都不執行 worker，等下一次觸發；daily 另在 `schedule_runs` 留一列 `skipped` 與原因，news 只寫日誌。全市場 analyze＋evaluate＋candidates＋indicators 峰值約 0.3 GB（[限制](../SCHEDULING.md#限制)），daily 門檻 2 GB 保留 collect 與其他程式的餘裕。

**執行的版本**（#314、#340）：job 不更新程式，程式是 [`deploy.sh`](../../RELEASE.md#部署) 部署的 image。版本只有一套：image 的 `STOCK_IMAGE_TAG`（例如 `stock-lab-backend:v1.1.0`）與 `STOCK_GIT_HEAD`（該 tag 的 commit）。job 把兩者寫進日誌（`--- version image=<…> head=<…>`，沒有時 `unknown`），daily 記在 run 列的 `summary_json.runtime`（[日誌與 run 記錄](../SCHEDULING.md#日誌與-run-記錄)）；job 不執行 git。舊命令帶的 `--git-pull`，job 照收、不 pull，日誌記一列 `--- --git-pull ignored`。

## 看門狗與事件 monitor 的工作

正式的看門狗與事件 monitor 由 scheduler 容器的 serve 執行（[排程看門狗](../WATCHDOG.md)、[統籌事件 monitor](../MONITOR.md)），判定、日誌與鎖兩邊相同。切換前它們是工作排程器的 `\stock-lab\monitor`（常駐，#316，以 `tools/ops/Register-Monitor.ps1` 註冊）與 `\stock-lab\watchdog`（每 15 分鐘，以 `tools/ops/Register-Watchdog.ps1` 註冊）；工作與腳本都已移除（#683），命令見刪除前的版本（本文開頭的連結）。手動一輪仍是 `bash tools/ops/monitor.sh --once --record-only`、`bash tools/ops/watchdog.sh --dry-run`，手動核對某交易日是 `python tools/ops/watchdog_helper.py data-check <stock.db> <YYYY-MM-DD> [--offline] [--all]`（唯讀，不記日誌、不留言）。
