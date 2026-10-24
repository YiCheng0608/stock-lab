---
name: verify-stock-lab
description: 對 stock-lab 五個主導航（今日、新聞、族群、個股、行動）做端到端驗證並留下可重跑的證據。兩種模式：CI 模式由 CI `verify` job 在假資料庫上自動跑（本機可重跑）；真資料模式在 gate 收尾時於本機用正式 DB 的唯讀副本跑 `page_checks.py`，agent 只做標「人工」的檢查與判讀，輸出每個導覽的三態結果（通過／失敗／無法判定）與截圖、API 回應、DB 查詢。G7 驗收、gate 收尾或使用者說「跑 verify-stock-lab」時使用。
---

# verify-stock-lab

檢查項目寫在 [`features/*.md`](features/README.md)：類型 `CI` 的由 [`tools/verify/page_checks.py`](../../../tools/verify/page_checks.py) 自動跑，`人工` 的由 agent 判斷。兩種模式跑的是同一份程式與 features 檔，差在資料與時機：

| 模式 | 什麼時候 | 資料 | 誰跑 |
| --- | --- | --- | --- |
| [CI 模式](#ci-模式) | 每個 PR 與 master push | 假資料庫（[`fixture_db.py`](../../../tools/verify/fixture_db.py)），數值固定 | CI `verify` job，自動 |
| [真資料模式](#真資料模式) | 每個 gate 收尾、每合併約 3 個 PR、G7（[工作手冊](../../../docs/GITHUB_WORKFLOW.md#任務流程)第 6 步） | 正式 DB 的唯讀副本（`tools/ops/copy_db.py`） | 統籌在以最新 `origin/master` 為底的任務 worktree 另開 session |

回覆使用者一律繁體中文。所有命令在 Git Bash（Claude Code 的 Bash 工具）執行，cwd 為 worktree 根目錄。

## CI 模式

CI `verify` job（`.github/workflows/ci.yml`）每次：

1. 跑 [`tools/verify/verify_plan.py`](../../../tools/verify/verify_plan.py)，依 PR 改到的檔案決定要驗哪幾頁（規則在 [features 驗證範圍](features/README.md#驗證範圍)），plan 寫進 job summary。一頁都不用驗時其餘步驟全部跳過，job 仍以 success 結束。
2. 用 `fixture_db.py` 建假資料庫，建置前端，在 runner 上起 API 與 vite preview（[`tools/verify/vite.preview.mjs`](../../../tools/verify/vite.preview.mjs)）。
3. 跑 `page_checks.py --fixture --pages <plan 的頁>`：每頁的 `CI` 檢查，加上 `API` 檢查（頁面用到的 API 回應等於 `fixture_data.EXPECTED`）。`KNOWN_FAILURES` 列出的已知產品缺陷照報但不讓 job 失敗，修好後要從清單移除。
4. 結果寫進 job summary；`out/`（API JSON、截圖、`summary.md`、`results.json`）與 `logs/` 上傳成 artifact `verify-<attempt>`，保留 14 天。

### 本機重跑

CI 失敗想在本機重現，或改了 verify 工具想先跑一次時用。需要後端依賴（下面借 release venv 的套件，不改它）與 `frontend/node_modules`（`pnpm --dir frontend install --frozen-lockfile`），用不到正式 DB，任何時段都可以跑。

```bash
WT="$(git rev-parse --show-toplevel)"; V="$WT/.local/verify/ci"; mkdir -p "$V/logs"
PY=C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe
export PYTHONPATH="$WT/backend;C:/Users/YiCheng/stock-lab-release/.venv/Lib/site-packages"
"$PY" -B "$WT/tools/verify/verify_plan.py" --base "$(git rev-parse origin/master)"   # 看 CI 會驗哪幾頁
"$PY" -B "$WT/tools/verify/fixture_db.py" --dest "$V/db" > "$V/logs/fixture.json"   # $V/db 須不存在或為空
```

接著照[起服務](#起服務)（`DB="$V/db/stock.db"`），再跑：

```bash
"$PY" -B "$WT/tools/verify/page_checks.py" --fixture --db "$V/db/stock.db" --out "$V/out" \
  --api "http://127.0.0.1:$API_PORT" --web "http://127.0.0.1:$WEB_PORT" [--pages today,news]
```

`$V/out/summary.md` 與 CI 的 job summary 同格式。做完照[收尾](#收尾)。

## 真資料模式

### 1. 前置

1. **停止條件**（任一成立就不跑，直接回覆原因）：
   - 台北時間 18:30～21:30（排程 `daily` 時段，不碰正式 DB）：`TZ=UTC-8 date +%H%M` 在 `1830`～`2130` 之間（POSIX 寫法的 UTC+8；Git Bash 沒有時區資料庫，`Asia/Taipei` 會被當成 UTC）。
   - 目前分支是 `master`（`git rev-parse --abbrev-ref HEAD`）：管理 checkout 不跑，請在任務 worktree 執行。
2. **變數**（Bash 工具不保留 shell 狀態，每個命令開頭重設）：

   ```bash
   WT="$(git rev-parse --show-toplevel)"; V="$WT/.local/verify"
   PY=C:/Users/YiCheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe
   export PYTHONPATH="$WT/backend;C:/Users/YiCheng/stock-lab-release/.venv/Lib/site-packages"
   OUT=$(cat "$V/current")   # 第 3 步寫入
   ```

   `$PY` 是 release venv 的基底直譯器（同為 3.12.14），借 venv 的套件跑 API；不直接執行 venv 的 `python.exe`，因為它是啟動器，真正監聽的是它的子程序，收尾時關不乾淨。
3. **輸出目錄**：`$OUT` 只算一次，之後一律從 `$V/current` 讀（跨分鐘重算會變成另一個目錄）。

   ```bash
   OUT="$V/out/$(TZ=UTC-8 date +%Y%m%d-%H%M)"; mkdir -p "$OUT" "$V/logs" && printf '%s\n' "$OUT" > "$V/current"
   ```

4. **副本**（唯讀複製，約 10 秒；已存在也重做，確保是最新快照）。正式 DB `C:/Users/YiCheng/stock-lab-data/stock.db` 只出現在這一行的 `--src`：

   ```bash
   "$PY" -B "$WT/tools/ops/copy_db.py" --src C:/Users/YiCheng/stock-lab-data/stock.db --dest "$V" --force > "$OUT/copy.json"
   ```

   失敗（exit 非 0）→ 五個導覽全部無法判定，原因寫 stderr，跳到[證據](#4-證據)。
5. **副本 revision**：`copy.json` 的 `alembic_version` 必須等於 `backend/app/migration_revisions.py` 的 `REVISIONS` 最後一項，不相等 API 會拒絕啟動。本分支新增了 migration 時可以只對副本跑 `init-db`（`STOCK_DATA_DIR="$V" STOCK_DB_PATH="$V/stock.db" STOCK_RAW_DIR="$V/raw" "$PY" -B -m worker.cli init-db`，2 GB 副本約 36 分鐘，三個 `STOCK_*` 必須都指向 `$V`），否則全部無法判定。
6. **私人資料**：`"$PY" -B "$WT/.claude/skills/verify-stock-lab/db_facts.py" "$V/stock.db" > "$OUT/facts.json"`。`portfolio_positions` 大於 0 時今日與行動頁會出現庫存，本次是私人模式，見[私人資料](#私人資料)。

### 2. 起服務並跑 CI 檢查

照[起服務](#起服務)（`DB="$V/stock.db"`），再跑（私人模式把 `--out "$OUT"` 換成 `--out "$OUT/.private"`）：

```bash
"$PY" -B "$WT/tools/verify/page_checks.py" --db "$V/stock.db" --out "$OUT" \
  --api "http://127.0.0.1:$API_PORT" --web "http://127.0.0.1:$WEB_PORT" > "$V/logs/checks.log" 2>&1
```

約 3～5 分鐘。exit 0 全部通過、1 有失敗、2 是 features 檔與程式不一致（工具問題，五個導覽判無法判定並附 stderr）。輸出：`summary.md`（每頁每條檢查的結果與證據）、`results.json`、`api/`、`shots/`。

### 3. 人工檢查與判讀

1. 各 features 檔「檢查」表類型為 `人工` 的條目由 agent 做：讀 `shots/*.txt`、`shots/*.png`、`api/*.json`，照該條「怎麼判」記 `通過`／`失敗`／`無法判定` 與一句證據。目前沒有標人工的檢查時這步略過，summary 寫「無人工檢查」。
2. `page_checks.py` 判失敗或無法判定的每一條，選一個[原因類別](features/README.md#原因類別)（文件漂移、工具缺口、產品缺陷）。不改檢查讓它通過：判成文件漂移或工具缺口的照實記下，另開 PR 修。
3. 每個導覽的三態：任一條失敗 → 失敗；沒有失敗但有無法判定 → 無法判定；否則通過。

#### 人工檢查的共通規則

`page_checks.py` 實作了同一套規則；人工檢查照這裡做：

- 比對 API 字串與頁面文字前，兩邊都把空白正規化：換行（`\r`、`\n`）、全形空白（U+3000）與連續半形空白換成一個半形空白、去頭尾空白（瀏覽器的頁面文字會改寫空白）。tab 不動：表格列以 tab 分欄，檢查裡的 `\t` 就是 tab。
- 「下一行」指下一個非空白行（頁面文字有很多空行）。
- 截圖 JSON 的 `ready` 為 false、`missingClicks` 非空，或該頁依賴的 API 非 200 → 依賴它的檢查判「無法判定」（不是失敗），原因寫哪個 URL。
- 頁面文字與 API／DB 不一致 → 失敗，證據寫兩邊的值。
- 無資料時檢查的是空狀態文案，不是無法判定。
- 日期寫法：`D` 為 `YYYY-MM-DD`，`D/` 為同一天的 `YYYY/MM/DD`。
- 不修改任何程式或資料；不對 API 送 POST／PUT／DELETE。

### 4. 證據

1. 先照[收尾](#收尾)關服務、刪副本。
2. 在 `page_checks.py` 的 `summary.md`（私人模式是 `$OUT/summary.md`，見[私人資料](#私人資料)）最前面插入下列段落（可直接貼 PR 或 Issue），原有的各頁表格留在後面：

   ```markdown
   ## verify-stock-lab 真資料結果（2026-10-22 01:30 台北）

   - 程式：`task/227-verify-skill` @ `5fbf04c`（`git status --short` 有未 commit 的改動時，列出檔名並註明照工作樹建置）
   - 副本：資料日 2026-10-21（`facts.json` 的 `market_latest_trading_date`），alembic `0016_group_score_archive`，複製 10.1 秒
   - 證據：https://github.com/YiCheng0608/stock-lab/tree/pr-assets/227/20261022-0130
   - 人工檢查：無

   | 導覽 | 結果 | 失敗或無法判定的檢查（原因類別） |
   | --- | --- | --- |
   | 今日 `/` | 通過 | — |
   | 新聞 `/news` | 通過 | — |
   | 族群 `/themes` | 失敗 | G2：族群榜缺資料日期標記（產品缺陷） |
   | 個股 `/stocks` | 通過 | — |
   | 行動 `/actions` | 無法判定 | A1：`/api/actions?limit=20` 回 500（產品缺陷） |
   ```

   範例的數值與結論是虛構的。
3. **推送**：分支名為 `task/<n>-...` 時 `bash "$WT/tools/ops/push_pr_assets.sh" --issue <n> --dir "$OUT"`（`.private/` 等隱藏項目不推；不要把輸出接到 `head`，會讓推送中斷），「證據」行就是它印出的第二行（`https://github.com/YiCheng0608/stock-lab/tree/pr-assets/<n>/<$OUT 的目錄名>`）。分支不是 `task/<n>-...` 時不推送，證據行寫 `$OUT` 的本機路徑。
4. 最後回覆：summary 全文。不自行在 Issue 或 PR 留言，由呼叫者決定貼到哪裡。

### 私人資料

私人模式（`facts.json` 的 `portfolio_positions` 大於 0）時，`page_checks.py` 的輸出整個寫到 `$OUT/.private/`（不推送），並 `mv "$OUT/copy.json" "$OUT/.private/"`。推送的 summary 改用 `page_checks.py` 同時寫出的 `status.md`（同樣的表格，只有每條檢查的結果，不含證據文字）：`cp "$OUT/.private/status.md" "$OUT/summary.md"`，再照[證據](#4-證據)第 2 步在前面加段落並註明「私人模式」；人工檢查的證據只寫檔名、行號與行數。

## 起服務

兩種模式共用。每個命令開頭先重設該模式的變數（`WT`、`V`、`PY`、`PYTHONPATH`），另加 `DB`：要讀的資料庫，API 的三個 `STOCK_*` 永遠指向它所在的目錄。埠每次向作業系統要空埠，所以多個 worktree 可以同時跑。

1. **埠**：

   ```bash
   free() { "$PY" -c "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); print(s.getsockname()[1])"; }
   printf 'API_PORT=%s\nWEB_PORT=%s\n' "$(free)" "$(free)" > "$V/ports"
   ```

   之後每個命令開頭 `. "$V/ports"`。
2. **前端建置**（約 15 秒；`VITE_API_BASE` 用完整 URL，Git Bash 會把 `/api` 改寫成路徑）：

   ```bash
   . "$V/ports"; cd "$WT/frontend" && COREPACK_ENABLE_DOWNLOAD_PROMPT=0 corepack pnpm@10.18.3 install --frozen-lockfile \
     && VITE_API_BASE="http://127.0.0.1:$WEB_PORT/api" node node_modules/vite/bin/vite.js build --outDir "$V/dist" --emptyOutDir > "$V/logs/build.log" 2>&1
   ```

3. **API**（Bash 工具 `run_in_background: true`；PID 寫進 `$V/api.pid`）：

   ```bash
   . "$V/ports"; D="$(dirname "$DB")"; cd "$WT" && STOCK_DATA_DIR="$D" STOCK_DB_PATH="$DB" STOCK_RAW_DIR="$D/raw" \
     "$PY" -B -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" > "$V/logs/api.log" 2>&1 & echo $! > "$V/api.pid"; wait
   ```

4. **前端**（同樣背景執行；PID 寫進 `$V/web.pid`）：

   ```bash
   . "$V/ports"; cd "$WT/frontend" && VERIFY_DIST="$V/dist" VERIFY_WEB_PORT="$WEB_PORT" VERIFY_API_URL="http://127.0.0.1:$API_PORT" \
     node node_modules/vite/bin/vite.js preview --config "$WT/tools/verify/vite.preview.mjs" > "$V/logs/preview.log" 2>&1 & echo $! > "$V/web.pid"; wait
   ```

5. **等就緒**（最多約 60 秒，不用 `sleep`）：

   ```bash
   . "$V/ports"; for url in "http://127.0.0.1:$API_PORT/api/health" "http://127.0.0.1:$WEB_PORT/api/health"; do
     curl -fsS -o /dev/null --retry 60 --retry-delay 1 --retry-connrefused --retry-all-errors "$url" || echo "not ready: $url"; done
   ```

   有 `not ready` → `$V/logs/api.log` 出現 `Database is not ready` 就抄該行；五個導覽全部無法判定，跳到收尾。

## 收尾

只關本 skill 啟動的程序、只刪本 skill 的暫存：

1. `kill $(cat "$V/api.pid") $(cat "$V/web.pid")`，再 `ps -p $(cat "$V/api.pid"),$(cat "$V/web.pid")` 確認兩個都已不在（只剩表頭）；背景工作因此回報 failed 屬預期。之後刪 `$V/api.pid`、`$V/web.pid`、`$V/ports`。
2. 刪 `$V/dist`；CI 模式另刪 `$V/db`；真資料模式另刪 `$V/raw`（API 啟動時建的空目錄）與 `$V/stock.db`（含同名 `-wal`、`-shm`、`-journal`、`.partial`），各用一行 `rm -rf` 寫完整路徑。保留 `$V/out/`（證據）與 `$V/logs/`。
3. `ls -a "$OUT/shots"`（私人模式看 `$OUT/.private/shots`）不應有 `.browser-*`（`screenshot.cjs` 自己會刪；殘留就刪掉並記在 summary 最後一段「清理」）。
4. 不刪 `frontend/node_modules`（下次重用）；不碰 `.local/verify` 以外的路徑。
