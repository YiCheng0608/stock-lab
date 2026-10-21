---
name: verify-stock-lab
description: 對 stock-lab 五個主導航（今日、新聞、族群、個股、行動）做端到端驗證並留下可重跑的證據。用正式 DB 的唯讀副本啟動 API 與 vite preview，逐一跑 features/*.md 的檢查，輸出每個導覽的三態結果（通過／失敗／無法判定）與截圖、API 回應、DB 查詢。G7 驗收、UI 任務自測或使用者說「跑 verify-stock-lab」時使用。
---

# verify-stock-lab

依序做五段：Launch → Doctor → Drive → Evidence → Cleanup（Evidence 的推送放在 Cleanup 之後，見 Evidence 第 3 步）。中途不需要人補指令；任何一段卡住就把受影響的導覽判為「無法判定」並寫明原因，照樣做完 Evidence 與 Cleanup。回覆使用者一律繁體中文。

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
| 輸出目錄 | `.local/verify/out/<YYYYMMDD-HHMM>/`（台北時間） |
| 台北時間 | `TZ=UTC-8 date '+%F %H:%M'` |

先設好變數（之後每個命令開頭都重設，Bash 工具不保留 shell 狀態）：

```bash
WT="$(git rev-parse --show-toplevel)"; V="$WT/.local/verify"
PY=C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe
APIPY=C:/Users/YiCheng/stock-lab-release/.venv/Scripts/python.exe
OUT="$V/out/<這次的 YYYYMMDD-HHMM>"   # 第一次設定後固定，用同一個值
```

## 1. Launch

1. **停止條件**（任一成立就不啟動，五個導覽全部「無法判定」，直接到 Evidence 寫原因）：
   - 台北時間 18:30～21:30（排程 `daily` 時段，不碰正式 DB）：`TZ=UTC-8 date +%H%M` 在 `1830`～`2130` 之間（POSIX 寫法的 UTC+8；Git Bash 沒有時區資料庫，`Asia/Taipei` 會被當成 UTC）。
   - 目前分支是 `master`（`git rev-parse --abbrev-ref HEAD`）：管理 checkout 不跑，請在任務 worktree 執行。
2. **埠**：`netstat -ano | grep LISTENING | grep -E ':(8227|4227) '`。有占用時依 Cleanup 第 1 步判斷是不是本 skill 先前留下的；是就關掉，不是就停止（無法判定：埠被其他程序占用）。
3. **建輸出目錄**：`mkdir -p "$OUT"/api "$OUT"/shots "$OUT"/results "$V"/logs`。耗時以 `echo "<段名> <epoch 秒>" >> "$OUT/.timing"` 記錄（隱藏檔，不推送）：Launch 用第 1 步開始時的 `date +%s`，Doctor、Drive、Evidence 各段開頭與 Drive 結束各記一行；summary 標題時間用這次的開始時間（與 `$OUT` 同一分鐘）。
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

背景程序被 Cleanup 的 `taskkill` 結束時，Bash 工具會通知該背景工作 failed（exit 1），屬預期。

8. **前端**（背景）：

   ```bash
   cd "$WT/frontend" && node node_modules/vite/bin/vite.js preview --config ../.claude/skills/verify-stock-lab/vite.preview.mjs > "$V/logs/preview.log" 2>&1
   ```

三個 `STOCK_*` 永遠指向 `$V`；任何命令出現 `stock-lab-data` 只能是第 4 步的 `--src`。

## 2. Doctor

1. 等 API（最多約 60 秒，不用 `sleep`）：`curl -s -o /dev/null -w '%{http_code}' --retry 60 --retry-delay 1 --retry-connrefused --retry-all-errors http://127.0.0.1:8227/api/health`。
2. 判定並寫進 `$OUT/doctor.txt`（每項一行 `項目 結果 說明`）：
   - `health`：`curl -s -i http://127.0.0.1:8227/api/health` 為 200 且本文含 `"status":"ok"`。
   - `readiness`：`$V/logs/api.log` 有 `Application startup complete`；出現 `Database is not ready` 就失敗並抄該行。
   - `proxy`：`curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:4227/api/health` 為 200，且 `http://127.0.0.1:4227/` 回 HTML。
   - `facts`：`"$PY" -B "$WT/.claude/skills/verify-stock-lab/db_facts.py" "$V/stock.db" > "$OUT/facts.json"` 成功。
3. 任一項失敗 → 五個導覽全部無法判定（原因寫失敗項），跳到 Evidence。
4. **私人資料**：`facts.json` 的 `portfolio_positions` 大於 0 時，今日與行動頁會出現庫存，本次所有截圖與 API JSON 改寫到 `$OUT/.private/`（不推送），摘要註明。

## 3. Drive

依序執行 `features/today.md`、`features/news.md`、`features/themes.md`、`features/stocks.md`、`features/actions.md`（同目錄）。後面的檔案會用前面記下的值（族群 → 個股 → 行動走同一條路徑），順序不可換。導覽代號固定用英文檔名 `today`、`news`、`themes`、`stocks`、`actions`（`push_pr_assets.sh` 只收 ASCII 檔名）。每個檔案：

1. 依「API」小節抓 JSON 存 `$OUT/api/<檔名>`（`curl -s -o <檔> -w '%{http_code}'`，非 200 記下）。
2. 依「截圖」小節跑 `node "$WT/tools/ops/screenshot.cjs" --url <頁> --out "$OUT/shots" [...]`，把 stdout 追加到 `$OUT/shots/<導覽代號>.jsonl`。每行 JSON 的 `txt` 是頁面文字檔的路徑，檢查都對檔案內容做（`grep -Fx` 比整行、`grep -F` 比片段）；需要時再看 `png`。
3. 逐條跑「檢查」，每條記 `通過`／`失敗`／`無法判定` 與一句證據（預期值、實際值、來源檔與行號）。
4. 依「判定」小節得出該導覽的三態，照「輸出格式」寫 `$OUT/results/<導覽代號>.md`。各 features 檔的輸出格式範例只示範格式，數值與結論是虛構的。

共通規則：

- 比對 API 字串與頁面文字前，兩邊都把空白正規化：換行（`\r`、`\n`）、全形空白（U+3000）與連續半形空白換成一個半形空白、去頭尾空白（瀏覽器的頁面文字會改寫空白）。tab 不動：表格列以 tab 分欄，檢查裡的 `\t` 就是 tab。
- 「下一行」指下一個非空白行（頁面文字有很多空行）。
- 一個導覽同時有失敗與無法判定的檢查時，結果是失敗，兩種都列出。
- 「有 AI 判讀」與前端 `usableAi` 相同：`ai.status` 為 `done` 且 `ai.inference` 為 true（方向欄位是 `ai.impact_direction`）。
- DB 與 API 裡沒有時區的時間（例如 `news_items.published_at`、`ai.generated_at`）是 UTC，與台北時間比較前加 8 小時。
- 截圖 JSON 的 `ready` 為 false、`missingClicks` 非空，或該頁依賴的 API 非 200 → 依賴它的檢查判「無法判定」（不是失敗），原因寫哪個 URL。
- 頁面文字與 API／DB 不一致 → 失敗，證據寫兩邊的值。
- 無資料時檢查的是空狀態文案，不是無法判定。
- 日期寫法：`D` 為 `YYYY-MM-DD`，`D/` 為同一天的 `YYYY/MM/DD`（`${D//-//}`）。
- 不修改任何程式或資料；不對 API 送 POST／PUT／DELETE。

## 4. Evidence

1. 寫 `$OUT/summary.md`，格式如下（可直接貼 PR 或 Issue）：

   ```markdown
   ## verify-stock-lab 結果（2026-10-22 01:30 台北）

   - 程式：`task/227-verify-skill` @ `5fbf04c`（`git status --short` 有未 commit 的改動時，列出檔名並註明照工作樹建置）
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
2. **證據連結**：分支名為 `task/<n>-...` 時取 `<n>`，「證據」行直接預填 `https://github.com/YiCheng0608/stock-lab/tree/pr-assets/<n>/<$OUT 的目錄名>`（推送後印出的第二行就是這個連結，核對一致）。分支不是 `task/<n>-...` 時不推送，證據行寫 `$OUT` 的本機路徑。
3. 先做 Cleanup，再回來推送：Cleanup 有任何異常（命令列不符沒關、殘留目錄）就追加到 summary 的最後一段「清理」，然後執行 `bash "$WT/tools/ops/push_pr_assets.sh" --issue <n> --dir "$OUT"`（`.private/`、`.timing` 等隱藏項目不推；不要把輸出接到 `head`，會讓推送中斷）。
4. 最後回覆：summary 全文。不自行在 Issue 或 PR 留言，由呼叫者決定貼到哪裡。

## 5. Cleanup

在 Evidence 第 3 步的推送之前做。只關本 skill 啟動的程序、只刪本 skill 的暫存：

1. 對 8227 與 4227 各做一次：`netstat -ano | grep LISTENING | grep ':<埠> '` 取 PID，用 `powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter 'ProcessId=<PID>').CommandLine"` 讀命令列；8227 必須含 `uvicorn` 與 `--port 8227`，4227 必須含 `vite.preview.mjs`，符合才 `taskkill //PID <PID> //T //F`，不符合就不動並在 summary 記下。8227 的監聽程序是 venv 啟動器的子程序，命令列顯示的是 codex runtime 的 `python.exe`，屬正常；`taskkill` 的輸出在 Git Bash 是亂碼，以下一步的 `netstat` 為準。
2. 再跑一次第 1 步的 `netstat`，兩個埠都不再 LISTENING。
3. 刪 `$V/dist`、`$V/raw`（API 啟動時建的空目錄）、`$V/stock.db`（含同名 `-wal`、`-shm`、`.partial`），各用一行 `rm -rf` 寫完整路徑。保留 `$V/out/`（證據）與 `$V/logs/`。
4. `ls -a "$OUT/shots"` 不應有 `.browser-*`（screenshot.cjs 自己會刪；殘留就刪掉並記下）。
5. 不刪 `frontend/node_modules`（下次重用）；不碰 `.local/verify` 以外的路徑。
