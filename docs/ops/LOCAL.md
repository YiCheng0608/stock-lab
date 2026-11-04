<!-- owns: 本機路徑、取正式 DB 唯讀副本的標準命令 -->
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
- **輸出**：一列 JSON，副本是 `$D/stock.db`（輸出裡的 `/out/stock.db` 是容器內路徑）。`source` 必須是 `/data/stock.db`；`alembic_version` 與 `source_latest_trading_date` 是驗收要貼的。`source_latest_trading_date` 要是最近一個交易日（當天的資料要等台北 18:30 之後的 daily 收完才有），落後就不是這個 volume 的現況，停下來查，不要拿去驗收。`$D/stock.db` 已存在時加 `--force`。
- **大小與時間**：2026-11-05 副本約 2.95 GB、229 秒（來源另有約 4 GB 的 WAL）；要留 DB 大小的磁碟。
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
| codebase-memory 同引擎 CLI | `C:/Users/YiCheng/.local/bin/codebase-memory-mcp.cmd` |
| worktree 外暫存目錄 | `C:/Users/YiCheng/t<issue>` |
