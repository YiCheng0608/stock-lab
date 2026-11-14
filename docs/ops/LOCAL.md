<!-- owns: 本機路徑、取正式 DB 唯讀副本的標準命令、session 起始 context 的專案設定 -->
# 本機路徑

這台主機上的實際路徑只寫在本文；其他文件與 skill 以名稱（例如「正式資料目錄」「發佈 checkout」）引用這裡。

## 正式位置（使用者決定）

使用者 2026-10-17 決定（[#1](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-6235674933)），用途見[排程](SCHEDULING.md)與 [daily／news 工作的註冊與管理](platform/windows.md#dailynews-工作的註冊與管理)。Docker 切換（#342）後，正式資料在 volume 裡，不在主機路徑：

| 名稱 | 路徑 |
| --- | --- |
| 正式資料目錄 | Docker volume `stock-lab_stock-data`（compose project `stock-lab`；容器內 `/data/`：`stock.db`、`raw/`、`logs/`、`locks/`）。主機沒有對應的檔案路徑，讀寫都經容器 |
| 正式 DB | 上述 volume 的 `/data/stock.db`（寫入中另有 `-wal`、`-shm`）。不在主機開檔；要驗收、比對或備份，照[取正式 DB 的唯讀副本](#取正式-db-的唯讀副本) |
| 主機的 `stock-lab-data/`（Docker 切換前的資料目錄） | `C:/Users/YiCheng/stock-lab-data/`：舊 `stock.db` 與 `raw/` 已於 2026-11-05 刪除（使用者決定，[#459](https://github.com/YiCheng0608/stock-lab/issues/459#issuecomment-6635662254)），現在只剩統籌的協作目錄 `logs/` 與切換前 job 留下的空鎖檔 `locks/`。這裡沒有任何 DB，不要放備份或副本 |
| 統籌的資料目錄的 `logs/`（正式 scheduler 的 `STOCK_COORDINATION_DIR`，[統籌事件 monitor](MONITOR.md)） | `C:/Users/YiCheng/stock-lab-data/logs` |
| 發佈 checkout | `C:/Users/YiCheng/stock-lab-release/` |
| 發佈 checkout 的 venv | `C:/Users/YiCheng/stock-lab-release/.venv`（套件在 `.venv/Lib/site-packages`） |
| 正式 DB 的手動備份（使用者 2026-11-05 決定，[#459](https://github.com/YiCheng0608/stock-lab/issues/459#issuecomment-6635662254)；含 migration 的部署前備份見 [RELEASE](../RELEASE.md#含-migration-的版本)，[#1 6635665869](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-6635665869)） | `C:/Users/YiCheng/stock-lab-backups/<用途>-<YYYYMMDD>/stock.db`，例如 `pre-v1.2.0-20261104`（含 migration 的部署前備份固定用 `pre-<tag>-<YYYYMMDD>`）。一律放在這裡，不放進 `stock-lab-data/`；取法同下節，`D` 換成備份目錄 |

## 取正式 DB 的唯讀副本

正式 DB 只在 volume 裡。驗收、驗證與備份都從 volume 取副本，不讀主機路徑：#452 曾照舊路徑取到 Docker 切換前的檔案，`ai` 欄位全是 null，之後才發現。在 Git Bash、任務 worktree 根目錄執行：

```bash
# 換值：D＝副本目錄。驗收與驗證放「工具」表的 worktree 外暫存目錄底下（例如 C:/Users/YiCheng/t<issue>/db）；備份放「正式位置」表的備份目錄
D=C:/Users/YiCheng/t<issue>/db; mkdir -p "$D"
IMG="$(docker inspect -f '{{.Config.Image}}' stock-lab-api-1)"   # 正在跑的 image，例如 stock-lab-backend:v1.2.0；不寫死版本
MSYS_NO_PATHCONV=1 docker run --rm --network none \
  -v stock-lab_stock-data:/data:ro -v "$D":/out \
  -v "$(git rev-parse --show-toplevel)/tools/ops/copy_db.py":/t/copy_db.py:ro \
  "$IMG" python /t/copy_db.py --src /data/stock.db --dest /out
```

- **為什麼這樣寫**：volume 以 `:ro` 掛、容器沒有網路，正式資料寫不到；`copy_db.py` 以 `mode=ro` 連線經 SQLite backup API 複製一份一致的快照，含 WAL（[CLI](CLI.md#測試與驗證)），所以 scheduler 與 api 照常執行，不必停。用跑著的 image（`docker inspect` 取 tag）是因為它的 SQLite 與寫入端同版本；`copy_db.py` 從 worktree 掛進去，不依賴 image 裡的版本。`MSYS_NO_PATHCONV=1` 只加在 `docker run` 這一行，不要 export：Git Bash 否則會把 `/data`、`/t` 改寫成 Windows 路徑，而 export 後容器外的 Windows Python 會把 `/c/Users` 讀成 `C:\c\Users`。
- **沒有連線開著時**（[#486](https://github.com/YiCheng0608/stock-lab/issues/486)）：scheduler 停了、api 也沒有開著的連線時，volume 裡只有 `stock.db`，沒有 `-wal`／`-shm`。這時唯讀掛載建不出 `-shm`，`mode=ro` 開不了，`copy_db.py` 改用 `immutable=1` 開主檔（主檔就是完整的 DB），輸出的 `source_open` 是 `immutable`（平常是 `ro`）。判斷條件與部署前的 [`db_revision.py`](../../tools/ops/db_revision.py) 是同一段程式。有 `-wal` 卻沒有 `-shm`、或有 hot `-journal` 時不讀，exit 1，訊息寫出是哪個檔：先讓 api 開一次 DB（打任一個 API），再重跑。immutable 不加鎖，所以複製完時旁邊多了 `-wal`、`-shm` 或 `-journal`，或主檔的修改時間、大小變了（有程式在途中開過 DB），副本會被刪掉並 exit 1，重跑即可。不要為此把 `:ro` 拿掉。
- **輸出**：一列 JSON，副本是 `$D/stock.db`（輸出裡的 `/out/stock.db` 是容器內路徑）。副本改名前要通過 `PRAGMA quick_check`，輸出的 `quick_check` 一定是 `ok`；不是 `ok`、備份失敗、來源中途不見都 exit 1，`$D` 不留 `stock.db.partial`。`source` 必須是 `/data/stock.db`；`alembic_version` 與 `source_latest_trading_date` 是驗收要貼的。`source_latest_trading_date` 要是最近一個交易日（當天的資料要等台北 18:30 之後的 daily 收完才有），落後就不是這個 volume 的現況，停下來查，不要拿去驗收。`$D/stock.db` 已存在時加 `--force`。
- **大小與時間**：2026-11-05 副本約 3.0 GB；加上 quick_check 共 463 秒（不含 quick_check 約 200～230 秒，來源另有約 4 GB 的 WAL）；要留 DB 大小的磁碟。
- **取了以後**：副本是獨立的檔案，後續工具照各自文件對它跑（[CLI](CLI.md#測試與驗證)、[verify-stock-lab 真資料模式](../../.claude/skills/verify-stock-lab/SKILL.md#真資料模式)、[DB 深度審查](../WORKFLOW.md#任務流程)）；不要把 `-v stock-lab_stock-data` 的 `:ro` 拿掉。

### 讀 raw 的工具

主機的 `raw/` 已刪（上表）。`raw_payloads.payload_path` 存的是 capture 當時的路徑：切換前是舊 Windows 路徑（`C:\Users\YiCheng\stock-lab-data\raw\...`），切換後是容器路徑（`/data/raw/...`）。讀 raw 的工具（`tools/audit/audit.py`、`tools/ops/data_check.py`，凡經 [`app.raw_paths.payload_file`](../../backend/app/raw_paths.py) 的）在主機直接跑時，這兩種路徑都不存在，讀不到 raw（audit 把用到 raw 的項目記成無法判定）。擇一：

- **在容器內跑，volume 唯讀掛在 `/data`**：新舊兩種路徑都找得到（舊路徑換成 `STOCK_RAW_DIR` 底下的同一相對路徑，image 預設 `/data/raw`）。副本掛在 `/db`，程式是目前的工作樹（`python -B` 不寫 `__pycache__`）：

  ```bash
  # 換值：D＝上節的副本目錄；OUT＝輸出目錄（不能在 /data 底下）；IMG 同上節；GIT_RO 見工作手冊「本機檢查」（讓 summary 的「工具」欄記到 commit，否則是 None）
  MSYS_NO_PATHCONV=1 docker run --rm --network none \
    -v stock-lab_stock-data:/data:ro -v "$D":/db:ro -v "$OUT":/out \
    -v "$(git rev-parse --show-toplevel)":/app:ro "${GIT_RO[@]}" \
    "$IMG" python -B tools/audit/audit.py --db /db/stock.db --out /out
  ```

  容器內 `audit.py` 以 `SC_AVPHYS_PAGES`（等於 `MemFree`，不含 page cache）量可用記憶體，剛讀過大檔就會報 `free memory 0.08 GB is under 5.0 GB` 而 exit 2（2026-11-05 取完副本後實測，當時 `MemAvailable` 約 6 GB）。先看容器裡 `grep MemAvailable /proc/meminfo`，確定夠 audit 用，再把 `--min-free-gb` 調低。
- **把 `STOCK_RAW_DIR` 指到一份 raw**（`audit.py` 用 `--raw-dir`）：只有舊 Windows 路徑會換成這個目錄底下的同一相對路徑；切換後的 `/data/raw/...` 不換，在容器外仍讀不到。raw 約 2.2 GB（2026-11-05），副本放 worktree 外暫存目錄，不放 `stock-lab-data/`。

## 工具

| 名稱 | 路徑 |
| --- | --- |
| 容器外的 Python（PATH 上的 python 是 Store stub） | `C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe` |
| codebase-memory 同引擎 CLI（`close_task.sh`／`dispatch.sh` 預設用它，`STOCK_CBM_CLI` 可覆寫；[程式索引](../WORKFLOW.md#程式索引)） | `C:/Users/YiCheng/.local/bin/codebase-memory-mcp.cmd` |
| master 索引的 project | `C-Users-YiCheng-Desktop-taiwan-stock-research`（root 是管理 checkout） |
| worktree 外暫存目錄 | `C:/Users/YiCheng/t<issue>` |

## session 起始 context 的專案設定

在 repo 開的每個 Claude Code session（統籌、工程師、review，也包括使用者自己開的 session）都會套用 repo 的 `.claude/settings.json`。裡面用下列鍵關掉這個專案用不到的東西，讓新 session 第一次呼叫的 context 從約 54K 降到約 31K（#712；決定見 [#712 留言 6877115861](https://github.com/YiCheng0608/stock-lab/issues/712#issuecomment-6877115861)）。使用者層的設定檔不動，其他專案不受影響。

| 鍵 | 關掉什麼 | 理由與副作用 | 第一次呼叫省下 |
| --- | --- | --- | --- |
| `enabledPlugins` 四個 `…@claude-for-financial-services: false` | `financial-analysis`、`pitch-agent`、`gl-reconciler`、`market-researcher`：38 個 skill、3 個 agent 類型，以及連不上的 `mtnewswire` MCP | 專案沒有用到；專案層會蓋過使用者層的啟用 | 約 3.6K |
| `disableClaudeAiConnectors: true` | claude.ai 連接器（Gmail、Google Calendar、Google Drive、Claude Docs） | 專案沒有用到；連上後每一回合約 1.7K。官方文件寫明任一層設 true 就關，**local 層與 `--settings` 都開不回來**；要用連接器時，照下面「單一 session 開回來」的命令開，或到 repo 以外的目錄開 session | 約 0.7K |
| `enableArtifact: false` | Artifact 工具，以及系統提示裡對應的段落 | 專案用 GitHub 交付，沒有用到。PreToolUse 守門 matcher 裡的 `Artifact` 留著無害 | 約 12.5K（三項合計 16.1K 扣掉另兩項的估計）|
| `permissions.deny: ["SendFeedback"]` | SendFeedback 工具 | 沒有用到。`AskUserQuestion` 保留，使用者直接對話的 session 會用它；`ReportFindings` 保留，`/code-review` 要用它 | 約 1.8K（估：與保留的 AskUserQuestion 同大小，AskUserQuestion 實測 1,772）|
| `skillOverrides` 26 個 `"off"` | `dataviz`、`artifact-*`、`claude-in-chrome`、`claude-api`、`anthropic-skills:*` 等專案用不到的 skill | 不用 `disableBundledSkills`，因為它會連 `code-review` 一起關 | 約 4.9K |

hooks 與 PreToolUse 守門不屬於這一節，改上面這些鍵時不要動到它們。

**怎麼驗**（改了這些鍵、或升級 Claude Code 之後）：在 repo 用統籌的啟動參數開一個可見 terminal，命令是 `STOCK_TURN_HOOK=off claude --model <統籌模型> --effort <統籌 effort> --autocompact 400k 'Reply with just ok. Do not call any tools.'`。回覆後 `/exit`，讀這個 session 紀錄檔（`<CLAUDE_CONFIG_DIR>/projects/<專案目錄>/<session id>.jsonl`）第一筆 assistant 的 `usage`，加總 `input_tokens`、`cache_read_input_tokens`、`cache_creation_input_tokens`，門檻是 **55K**。

- `STOCK_TURN_HOOK=off` 一定要帶，否則 turn hook 會把這個 session 記成工程師 session。
- `claude -p` 沒有 Artifact、AskUserQuestion 等互動模式才有的工具，量出來偏低，不能拿來驗門檻。
- 同時核對工具清單（紀錄檔裡的 `api-request-shape`）沒有 Artifact、SendFeedback；skill 清單裡仍有 `code-review`、`orca-cli`、`encode-lesson`。
- 2026-11-14 用 Claude Code 2.1.325、`claude-opus-5-5`／`xhigh` 量到 30,634（worktree）與 30,323（管理 checkout，以 `--settings` 模擬）。

**單一 session 開回來**：`enableArtifact` 與 `skillOverrides` 在 local 層（`.claude/settings.local.json`）或 `--settings` 設回去都沒有效果（#712 實測）。要用時，在 repo 根目錄這樣開：

```bash
claude --setting-sources user,local --settings "$(node -e 'console.log(JSON.stringify({hooks: require("./.claude/settings.json").hooks}))')"
```

- `--setting-sources user,local` 不載入專案設定；`--settings` 只把專案的 hooks 帶回來，所以 `.env` 守門與 turn hook 照常。目前專案設定裡除了 hooks，只有上表這幾個為了省 context 而關的鍵；之後專案設定多了 hooks 以外、跟安全有關的規則（例如 `permissions.deny` 擋危險命令），這條命令的 `--settings` 要把那些鍵一起帶上。
- 代價是上表各項全部回到使用者層的狀態，第一次呼叫回到約 54K。這種 session 只拿來用 Artifact 或被關的 skill，不要拿來當統籌或工程師。
- claude.ai 連接器也會一起回來（實測 Claude Docs 有出現）。這是因為整份專案設定都沒有載入，不是 local 層開得回來。

MEMORY.md 索引約佔 7K（`autoMemoryEnabled:false` 量到的差），精簡由統籌處理（#705）。
