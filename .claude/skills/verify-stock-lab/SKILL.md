---
name: verify-stock-lab
description: 對 stock-lab 五個主導航（今日、新聞、族群、個股、行動）做端到端驗證並留下可重跑的證據。用正式 DB 的唯讀副本啟動 API 與 vite preview，逐一跑 features/*.md 的檢查，輸出每個導覽的三態結果（通過／失敗／無法判定）與截圖、API 回應、DB 查詢。G7 驗收、UI 任務自測或使用者說「跑 verify-stock-lab」時使用。
---

# verify-stock-lab

依序做五段：Launch → Doctor → Drive → Evidence → Cleanup。中途不需要人補指令；任何一段卡住就把受影響的導覽判為「無法判定」並寫明原因，照樣做完 Evidence 與 Cleanup。回覆使用者一律繁體中文。

所有命令在 Git Bash（Claude Code 的 Bash 工具）執行，cwd 為要驗證的 worktree 根目錄。長時間程序（API、preview）用 Bash 工具的 `run_in_background: true` 啟動，不要在命令尾端加 `&`。

## 固定值

| 名稱 | 值 |
| --- | --- |
| 正式 DB（只當 `copy_db.py --src`，其他命令一律不碰） | `C:/Users/YiCheng/stock-lab-data/stock.db` |
| 副本與暫存 | `<worktree>/.local/verify/`（gitignore）；副本 `.local/verify/stock.db` |
| 工具 Python（只用標準庫） | `C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe` |
| API Python（有後端依賴） | `C:/Users/YiCheng/stock-lab-release/.venv/Scripts/python.exe`（只讀用它的套件，不改這個 venv） |
| API | `http://127.0.0.1:8227` |
| 前端（vite preview，`/api` 轉給 8227） | `http://127.0.0.1:4227`，設定檔 `.claude/skills/verify-stock-lab/vite.preview.mjs` |
| 輸出目錄 | `.local/verify/out/<YYYYMMDD-HHMM>/` |

先設好變數（之後每個命令開頭都重設，Bash 工具不保留 shell 狀態）：

```bash
WT="$(git rev-parse --show-toplevel)"; V="$WT/.local/verify"
PY=C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe
APIPY=C:/Users/YiCheng/stock-lab-release/.venv/Scripts/python.exe
OUT="$V/out/<這次的 YYYYMMDD-HHMM>"   # 第一次設定後固定，用同一個值
```

## 1. Launch

1. **停止條件**（任一成立就不啟動，五個導覽全部「無法判定」，直接到 Evidence 寫原因）：
   - 台北時間 18:30～21:30（排程 `daily` 時段，不碰正式 DB）：`TZ=Asia/Taipei date +%H%M` 在 `1830`～`2130` 之間。
   - 目前分支是 `master`（`git rev-parse --abbrev-ref HEAD`）：管理 checkout 不跑，請在任務 worktree 執行。
2. **埠**：`netstat -ano | grep LISTENING | grep -E ':(8227|4227) '`。有占用時依 Cleanup 第 1 步判斷是不是本 skill 先前留下的；是就關掉，不是就停止（無法判定：埠被其他程序占用）。
3. **建輸出目錄**：`mkdir -p "$OUT"/api "$OUT"/shots "$OUT"/results "$V"/logs`，記下開始時間。
4. **副本**（唯讀複製，約 10 秒；副本已存在也重做，確保是最新快照）：

   ```bash
   "$PY" -B "$WT/tools/ops/copy_db.py" --src C:/Users/YiCheng/stock-lab-data/stock.db --dest "$V" > "$OUT/copy.json"
   ```

   失敗（exit 非 0）→ 全部無法判定，原因寫 stderr。
5. **副本 revision**：`copy.json` 的 `alembic_version` 必須等於 `backend/app/migration_revisions.py` 的 `REVISIONS` 最後一項。不相等時 API 會拒絕啟動：若本分支新增了 migration，可以只對副本跑 `init-db`（`STOCK_DATA_DIR="$V" STOCK_DB_PATH="$V/stock.db" STOCK_RAW_DIR="$V/raw" PYTHONPATH="$WT/backend" "$APIPY" -B -m worker.cli init-db`，2 GB 副本約 36 分鐘，三個 `STOCK_*` 必須都指向 `$V`），否則全部無法判定。
6. **前端建置**（約 15 秒；`VITE_API_BASE` 用完整 URL，Git Bash 會把 `/api` 改寫成路徑）：

   ```bash
   cd "$WT/frontend" && COREPACK_ENABLE_DOWNLOAD_PROMPT=0 corepack pnpm@10.18.3 install --frozen-lockfile \
     && VITE_API_BASE=http://127.0.0.1:4227/api node node_modules/vite/bin/vite.js build --outDir "$V/dist" --emptyOutDir > "$V/logs/build.log" 2>&1
   ```

7. **API**（背景）：

   ```bash
   cd "$WT" && STOCK_DATA_DIR="$V" STOCK_DB_PATH="$V/stock.db" STOCK_RAW_DIR="$V/raw" PYTHONPATH="$WT/backend" \
     "$APIPY" -B -m uvicorn app.main:app --host 127.0.0.1 --port 8227 > "$V/logs/api.log" 2>&1
   ```

8. **前端**（背景）：

   ```bash
   cd "$WT/frontend" && node node_modules/vite/bin/vite.js preview --config ../.claude/skills/verify-stock-lab/vite.preview.mjs > "$V/logs/preview.log" 2>&1
   ```

三個 `STOCK_*` 永遠指向 `$V`；任何命令出現 `stock-lab-data` 只能是第 4 步的 `--src`。

## 2. Doctor

1. 等 API：`for i in $(seq 1 60); do c=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8227/api/health); [ "$c" = 200 ] && break; sleep 1; done`。
2. 判定並寫進 `$OUT/doctor.txt`（每項一行 `項目 結果 說明`）：
   - `health`：`curl -s -i http://127.0.0.1:8227/api/health` 為 200 且本文含 `"status":"ok"`。
   - `readiness`：`$V/logs/api.log` 有 `Application startup complete`；出現 `Database is not ready` 就失敗並抄該行。
   - `proxy`：`curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:4227/api/health` 為 200，且 `http://127.0.0.1:4227/` 回 HTML。
   - `facts`：`"$PY" -B "$WT/.claude/skills/verify-stock-lab/db_facts.py" "$V/stock.db" > "$OUT/facts.json"` 成功。
3. 任一項失敗 → 五個導覽全部無法判定（原因寫失敗項），跳到 Evidence。
4. **私人資料**：`facts.json` 的 `portfolio_positions` 大於 0 時，今日與行動頁會出現庫存，本次所有截圖與 API JSON 改寫到 `$OUT/.private/`（不推送），摘要註明。

## 3. Drive

依序執行 `features/today.md`、`features/news.md`、`features/themes.md`、`features/stocks.md`、`features/actions.md`（同目錄）。後面的檔案會用前面記下的值（族群 → 個股 → 行動走同一條路徑），順序不可換。每個檔案：

1. 依「API」小節抓 JSON 存 `$OUT/api/<名稱>.json`（`curl -s -o <檔> -w '%{http_code}'`，非 200 記下）。
2. 依「截圖」小節跑 `node "$WT/tools/ops/screenshot.cjs" --url <頁> --out "$OUT/shots" [...]`，把 stdout 追加到 `$OUT/shots/<導覽>.jsonl`。每行 JSON 的 `txt` 是頁面文字，檢查都對這些文字做（`grep -Fx` 比整行、`grep -F` 比片段）；需要時再看 `png`。
3. 逐條跑「檢查」，每條記 `通過`／`失敗`／`無法判定` 與一句證據（預期值、實際值、來源檔）。
4. 依「判定」小節得出該導覽的三態，照「輸出格式」寫 `$OUT/results/<導覽>.md`。

共通規則：

- 截圖 JSON 的 `ready` 為 false、`missingClicks` 非空，或該頁依賴的 API 非 200 → 依賴它的檢查判「無法判定」（不是失敗），原因寫哪個 URL。
- 頁面文字與 API／DB 不一致 → 失敗，證據寫兩邊的值。
- 無資料時檢查的是空狀態文案，不是無法判定。
- 日期寫法：`D` 為 `YYYY-MM-DD`，`D/` 為同一天的 `YYYY/MM/DD`（`${D//-//}`）。
- 不修改任何程式或資料；不對 API 送 POST／PUT／DELETE。

## 4. Evidence

1. 寫 `$OUT/summary.md`，格式如下（可直接貼 PR 或 Issue）：

   ```markdown
   ## verify-stock-lab 結果（2026-10-22 01:30 台北）

   - 程式：`task/227-verify-skill` @ `5fbf04c`
   - 副本：資料日 2026-10-21（`market_bars` 最新），alembic `0016_group_score_archive`，複製 10.1 秒
   - Doctor：health 200、readiness 通過、proxy 200
   - 證據：https://github.com/YiCheng0608/stock-lab/tree/pr-assets/227/20261022-0130

   | 導覽 | 結果 | 失敗或無法判定的檢查 |
   | --- | --- | --- |
   | 今日 `/` | 通過 | — |
   | 新聞 `/news` | 通過 | — |
   | 族群 `/themes` | 失敗 | G2：族群榜缺資料日期標記（預期 `資料 2026/10/21`，`themes-1280.txt` 第 18 行為表格說明） |
   | 個股 `/stocks` | 通過 | — |
   | 行動 `/actions` | 無法判定 | A1：`/api/actions?limit=20` 回 500 |

   路徑：今日 #1 產業「鋼鐵」→ 族群詳情 → 個股 TWSE 2002 → 行動 TWSE 2002。
   耗時：Launch 0:45、Doctor 0:05、Drive 4:10。
   ```

   下面接各導覽的 `results/*.md` 原文。
2. **推送**：分支名為 `task/<n>-...` 時取 `<n>`，執行 `bash "$WT/tools/ops/push_pr_assets.sh" --issue <n> --dir "$OUT"`（`.private/` 等隱藏項目不推），把印出的樹狀連結填回 summary 的「證據」行。分支不是 `task/<n>-...` 時不推，證據行寫本機路徑。
3. 最後回覆：summary 全文。不自行在 Issue 或 PR 留言，由呼叫者決定貼到哪裡。

## 5. Cleanup

只關本 skill 啟動的程序、只刪本 skill 的暫存：

1. 對 8227 與 4227 各做一次：`netstat -ano | grep LISTENING | grep ':<埠> '` 取 PID，用 `powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter 'ProcessId=<PID>').CommandLine"` 讀命令列；8227 必須含 `uvicorn` 與 `--port 8227`，4227 必須含 `vite.preview.mjs`，符合才 `taskkill //PID <PID> //T //F`，不符合就不動並在摘要記下。
2. 再跑一次第 1 步的 `netstat`，兩個埠都不再 LISTENING。
3. 刪 `$V/dist`、`$V/stock.db`（含同名 `-wal`、`-shm`、`.partial`），各用一行 `rm -rf` 寫完整路徑。保留 `$V/out/`（證據）與 `$V/logs/`。
4. `ls -a "$OUT/shots"` 不應有 `.browser-*`（screenshot.cjs 自己會刪；殘留就刪掉並記下）。
5. 不刪 `frontend/node_modules`（下次重用）；不碰 `.local/verify` 以外的路徑。
