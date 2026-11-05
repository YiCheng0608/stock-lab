---
name: verify-stock-lab
description: 對 stock-lab 五個資料與行動頁（今日可買、觀察中、族群、個股、新聞；策略說明是靜態頁，由前端測試涵蓋）做端到端驗證並留下可重跑的證據。兩種模式：CI 模式由 CI `verify` job 在假資料庫上自動跑（本機可重跑）；真資料模式在 gate 收尾與 G7 窗口頭尾時用正式 DB 的唯讀副本跑 `page_checks.py`（容器內；G7 在本機），agent 只判讀標「人工」的檢查（樣本由程式依規則抽好）與失敗原因，輸出每個導覽的三態結果（通過／失敗／無法判定）與截圖、API 回應、DB 查詢。G7 驗收、gate 收尾或使用者說「跑 verify-stock-lab」時使用。
---

# verify-stock-lab

檢查項目寫在 [`features/*.md`](features/README.md)：類型 `CI` 的由 [`tools/verify/page_checks.py`](../../../tools/verify/page_checks.py) 自動跑，`人工` 的由 agent 判斷。兩種模式跑的是同一份程式與 features 檔，差在資料與時機：

| 模式 | 什麼時候 | 資料 | 誰跑 |
| --- | --- | --- | --- |
| [CI 模式](#ci-模式) | 每個 PR 與 master push；master 每晚 22:40（台北）與手動觸發（`workflow_dispatch`）跑五頁全套 | 假資料庫（[`fixture_db.py`](../../../tools/verify/fixture_db.py)），數值固定 | CI `verify` job，自動 |
| [真資料模式](#真資料模式) | 每個 gate 收尾、每合併約 3 個 PR、G7 的 5 個交易日窗口開頭與結尾各一次（[工作手冊](../../../docs/WORKFLOW.md#任務流程)第 6 步、[RELEASE 的 V1 發佈隔離](../../../docs/RELEASE.md#v1-發佈隔離g7-窗口專用)） | 正式 DB 的唯讀副本（`tools/ops/copy_db.py`），容器跑法放在 compose volume | 統籌在以最新 `origin/master` 為底的任務 worktree 另開 session |

回覆使用者一律繁體中文。所有命令在 Git Bash（Claude Code 的 Bash 工具）執行，cwd 為 worktree 根目錄。

## CI 模式

CI `verify` job（`.github/workflows/ci.yml`）每次：

1. 跑 [`tools/verify/verify_plan.py`](../../../tools/verify/verify_plan.py)，依 PR 改到的檔案決定要驗哪幾頁（規則在 [features 驗證範圍](features/README.md#驗證範圍)），plan 寫進 job summary。一頁都不用驗時其餘步驟全部跳過，job 仍以 success 結束。每晚排程（`schedule`）與手動觸發（`workflow_dispatch`）以 `--event` 選全部五頁。
2. 裝截圖用的 CJK 字型（[`tools/verify/install_fonts.sh`](../../../tools/verify/install_fonts.sh)，見下方[診斷](#診斷)），用 `fixture_db.py` 建假資料庫，建置前端，在 runner 上起 API 與 vite preview（[`tools/verify/vite.preview.mjs`](../../../tools/verify/vite.preview.mjs)）。
3. 跑 `page_checks.py --fixture --pages <plan 的頁>`：每頁的 `CI` 檢查，加上 `API` 檢查（頁面用到的 API 回應等於 `fixture_data.EXPECTED`）。結果是三態（[features 三態與上游](features/README.md#三態與上游)）；假資料庫每個值都在，所以 `--fixture` 下無法判定也讓 job 失敗。`KNOWN_FAILURES` 列出的已知產品缺陷只在失敗訊息含登記的片段時照報而不讓 job 失敗（[已知失敗](features/README.md#已知失敗)），修好後要從清單移除。
4. 結果寫進 job summary；`out/`（API JSON、截圖、`summary.md`、`results.json`）與 `logs/` 上傳成 artifact `verify-<attempt>`，保留 14 天。

### 診斷

job 失敗或被取消時，先看哪一步花了時間，再讀那一步的 log：

- **各步時間**：`gh api repos/YiCheng0608/stock-lab/actions/runs/<run>/attempts/<n>/jobs --jq '.jobs[] | select(.name=="verify") | .steps[] | "\(.name) \(.started_at) \(.completed_at) \(.conclusion)"'`。重跑過的 job 要指定 attempt；`gh run view --job` 只顯示最後一次。
- **整份 log**：`gh api --allow-escape-sequences repos/YiCheng0608/stock-lab/actions/jobs/<job_id>/logs`。
- **字型（`Fonts` 步驟）**：#489 時裸跑的 `apt-get` 曾 12～15 分鐘以上沒結束，把 job 拖到 15 分鐘上限。現在字型檔走 `actions/cache`（`Restore fonts`／`Save fonts`，各有步驟逾時與 `continue-on-error`，快取慢或壞掉只會退回 apt），命中時不碰 apt。沒命中才跑 `apt-get update`、`apt-get install`，各有上限並重試；step log 每個命令一行（開始、完成秒數，或 `逾時：<命令> 跑了 N 秒仍未結束`），逾時或失敗時印出 `logs/fonts.log`（含 apt 輸出）最後 40 行、還在跑的 apt／dpkg／http 行程與 apt 來源，以 `::error title=verify fonts::` 失敗結束。完整輸出在 artifact 的 `logs/fonts.log`。
- **API 與 preview**：`Start API and preview` 的 `curl --retry 60` 約 1 分鐘等不到 `/api/health` 就失敗；`Summary` 步驟印出 `logs/api.log`、`logs/preview.log` 最後 20 行。
- **檢查（`Checks` 步驟）**：步驟上限 8 分鐘；各頁結果在 job summary 與 artifact 的 `out/summary.md`，截圖在 `out/shots`。

### 本機重跑

CI 失敗想在本機重現，或改了 verify 工具想先跑一次時用。需要後端依賴（下面借 release venv 的套件，不改它；`<…>` 換成[本機路徑](../../../docs/ops/LOCAL.md)的值）與 `frontend/node_modules`（`pnpm --dir frontend install --frozen-lockfile`），用不到正式 DB，任何時段都可以跑。

```bash
# 換值（docs/ops/LOCAL.md）：<容器外的 Python>＝「工具」表的「容器外的 Python」；<發佈 checkout 的 venv>＝「正式位置」表的「發佈 checkout 的 venv」
WT="$(git rev-parse --show-toplevel)"; V="$WT/.local/verify/ci"; mkdir -p "$V/logs"
PY='<容器外的 Python>'
export PYTHONPATH="$WT/backend;<發佈 checkout 的 venv>/Lib/site-packages" PYTHONUTF8=1
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

### 容器或本機

| 跑法 | 什麼時候 | API、前端、`page_checks.py` 與截圖 | 副本 |
| --- | --- | --- | --- |
| 容器（預設） | checkout 有 `docker-compose.yml`，而且不是 G7 的那兩次 | compose project `$P`（`task-<n>-verify`）：api（後端 image）、web（nginx 前端 image）；`page_checks.py` 以 `run --rm api` 在同一個網路跑，截圖用後端 image 內的 Chromium | 該 project 的 volume `task-<n>-verify_stock-data` |
| 本機 | G7 的兩次（`release/v1` 沒有 compose 檔，`--g7` 照 [#260](https://github.com/YiCheng0608/stock-lab/issues/260) 在本機跑），或 checkout 沒有 compose 檔 | 本機的 Python、vite preview、Edge／Chrome（[起服務](#起服務)） | `$V/stock.db` |

同一份副本兩種跑法的三態結果相同（#339 比對兩邊的 `results.json`）。`<n>` 是分支名 `task/<n>-...` 的數字。下面各步標「容器」或「本機」的只照所選跑法做，沒標的兩種都做。compose 檔要 Docker Compose 2.24 以上（[Docker compose](../../../docs/ops/SETUP.md#docker-compose)）。

### 1. 前置

1. **停止條件**（任一成立就不跑，直接回覆原因）：
   - 台北時間 21:30～23:30（排程 `daily` 時段：21:30 與 23:00 的重試，#466；不碰正式 DB）：`TZ=UTC-8 date +%H%M` 在 `2130`～`2330` 之間（POSIX 寫法的 UTC+8；Git Bash 沒有時區資料庫，`Asia/Taipei` 會被當成 UTC）。
   - 目前分支是 `master`（`git rev-parse --abbrev-ref HEAD`）：管理 checkout 不跑，請在任務 worktree 執行。
   - G7 的那兩次：G7 證據必須是排程正在跑的發佈 branch 程式。先 `git fetch origin master release/v1`；worktree 要從當時的 `origin/release/v1` 建，沒有額外 commit、沒有未 commit 的改動（`--g7` 要求 HEAD 等於 `origin/release/v1`）。第 2 步加 `--g7`，`page_checks.py` 不符合就 exit 2 並寫明原因，不跑任何檢查。
2. **變數**（Bash 工具不保留 shell 狀態，每個命令開頭重設；`<…>` 換成[本機路徑](../../../docs/ops/LOCAL.md)的值）：

   ```bash
   # 換值（docs/ops/LOCAL.md）：<容器外的 Python>＝「工具」表的「容器外的 Python」；<發佈 checkout 的 venv>＝「正式位置」表的「發佈 checkout 的 venv」
   WT="$(git rev-parse --show-toplevel)"; V="$WT/.local/verify"
   PY='<容器外的 Python>'
   export PYTHONPATH="$WT/backend;<發佈 checkout 的 venv>/Lib/site-packages" PYTHONUTF8=1
   OUT=$(cat "$V/current")   # 第 3 步寫入
   # 容器：project 名稱與 compose 命令（Git Bash 不改寫 -v 的容器路徑）
   n="$(git rev-parse --abbrev-ref HEAD)"; n="${n#task/}"; P="task-${n%%-*}-verify"
   dc() { MSYS_NO_PATHCONV=1 docker compose -p "$P" "$@"; }
   ```

   `$PY` 是 release venv 的基底直譯器（同為 3.12.14），借 venv 的套件跑 API；不直接執行 venv 的 `python.exe`，因為它是啟動器，真正監聽的是它的子程序，收尾時關不乾淨。`PYTHONUTF8=1`：Windows 的 stdout 預設是 cp950，`page_checks.py` 印到含 `\xa0` 等字元的新聞標題會在寫完 summary 前中斷。
3. **輸出目錄**：`$OUT` 只算一次，之後一律從 `$V/current` 讀（跨分鐘重算會變成另一個目錄）。

   ```bash
   OUT="$V/out/$(TZ=UTC-8 date +%Y%m%d-%H%M)"; mkdir -p "$OUT" "$V/logs" && printf '%s\n' "$OUT" > "$V/current"
   ```

4. **副本**（唯讀複製，約 4 分鐘；已存在也重做，確保是最新快照）。正式 DB 在 Docker volume `stock-lab_stock-data` 裡，主機沒有檔案可複製（[本機路徑](../../../docs/ops/LOCAL.md#正式位置使用者決定)）。照 LOCAL 的[取正式 DB 的唯讀副本](../../../docs/ops/LOCAL.md#取正式-db-的唯讀副本)跑那一個命令，三處照這裡換：`D="$V"`、`python /t/copy_db.py` 後面加 `--force`、標準輸出存成 `$OUT/copy.json`。`source` 不是 `/data/stock.db`，或 `source_latest_trading_date` 不是最近一個已收完的交易日，就不是這個 volume 的現況，不繼續。

   失敗（exit 非 0）→ 五個導覽全部無法判定，原因寫 stderr，跳到[證據](#4-證據)。

   容器：再把副本複製進 volume（2.4 GB 約 1 分鐘）：

   ```bash
   dc run --rm --no-deps -v "$V:/src:ro" scheduler cp /src/stock.db /data/stock.db
   ```
5. **副本 revision**：`copy.json` 的 `alembic_version` 必須等於 `backend/app/migration_revisions.py` 的 `REVISIONS` 最後一項，不相等 API 會拒絕啟動。本分支新增了 migration 時可以只對副本跑 `init-db`（`STOCK_DATA_DIR="$V" STOCK_DB_PATH="$V/stock.db" STOCK_RAW_DIR="$V/raw" "$PY" -B -m worker.cli init-db`，2 GB 副本約 36 分鐘，三個 `STOCK_*` 必須都指向 `$V`），否則全部無法判定。容器：改對 volume 跑 `dc run --rm --no-deps scheduler python -B -m worker.cli init-db`（compose 把三個 `STOCK_*` 固定在 `/data`；用 scheduler 是因為它的記憶體上限 2 GB；0017→0020 在 2.4 GB 副本上約 3 分鐘，#339），`$V/stock.db` 不升級。
6. **私人資料**：`"$PY" -B "$WT/.claude/skills/verify-stock-lab/db_facts.py" "$V/stock.db" > "$OUT/facts.json"`。`portfolio_positions` 大於 0 時今日與行動頁會出現庫存，本次是私人模式，見[私人資料](#私人資料)。

### 2. 起服務並跑 CI 檢查

**容器**：埠向作業系統要空埠（`free` 見[起服務](#起服務)第 1 步），image 從工作樹 build（`STOCK_GIT_HEAD` 是 summary 與 run 記錄的程式版本），`--wait` 等 api 與 web 都 healthy；容器裡的 git 照[工作手冊「本機檢查」](../../../docs/WORKFLOW.md#本機檢查)的掛法讀這個 worktree。私人模式把 `--out /out` 換成 `--out /out/.private`：

```bash
printf 'API_PORT=%s\nWEB_PORT=%s\n' "$(free)" "$(free)" > "$V/ports"; set -a; . "$V/ports"; set +a
printf 'gitdir: /repo.git/worktrees/%s\n' "$(basename "$(git rev-parse --git-dir)")" > "$V/gitfile"
STOCK_GIT_HEAD="$(git rev-parse HEAD)" dc up -d --build --wait api web > "$V/logs/up.log" 2>&1 || dc logs api > "$V/logs/api.log" 2>&1
dc run --rm --no-deps -v "$(git rev-parse --git-common-dir):/repo.git:ro" -v "$V/gitfile:/app/.git:ro" -v "$OUT:/out" \
  api python -B tools/verify/page_checks.py --db /data/stock.db --out /out \
  --api http://api:8000 --web http://web:8080 > "$V/logs/checks.log" 2>&1
```

`up` 失敗時 `$V/logs/api.log` 出現 `Database is not ready` 就抄該行；五個導覽全部無法判定，跳到收尾。之後的命令開頭都要先 `set -a; . "$V/ports"; set +a`（compose 檔的埠從環境變數讀）。

**本機**：照[起服務](#起服務)（`DB="$V/stock.db"`），再跑（私人模式把 `--out "$OUT"` 換成 `--out "$OUT/.private"`）：

```bash
"$PY" -B "$WT/tools/verify/page_checks.py" --db "$V/stock.db" --out "$OUT" [--g7] \
  --api "http://127.0.0.1:$API_PORT" --web "http://127.0.0.1:$WEB_PORT" > "$V/logs/checks.log" 2>&1
```

約 3～5 分鐘。exit 0 沒有失敗（可能有無法判定）、1 有失敗、2 是 features 檔與程式不一致或 `--g7` 前置不符（不跑檢查；features 不一致時五個導覽判無法判定並附 stderr）。輸出：`summary.md`（開頭是程式版本、個股 `E`／`S` 的來源、三態計數與人工檢查樣本，接著每頁每條檢查的三態結果與證據）、`results.json`、`api/`、`shots/`、`manual/`（人工檢查樣本）。

### 3. 人工檢查與判讀

1. **人工檢查**（features 類型 `人工`）：樣本已由 `page_checks.py` 依寫死的規則抽好，在 `manual/<編號>.json`（規則寫在檔內 `rule` 與該條「怎麼判」）；不另挑、不增減樣本。判讀交給獨立 session：另開一個 Claude session，只給它 `$OUT` 路徑、features 檔與這一節，請它逐筆照「怎麼判」記 `通過`／`失敗`／`無法判定` 與一句證據（失敗寫樣本 id 與原句）；跑 `page_checks.py` 的 session 不自己判。樣本 0 筆或檔內有 `error` 時該條記無法判定。
2. `page_checks.py` 判失敗或無法判定的每一條，選一個[原因類別](features/README.md#原因類別)（文件漂移、工具缺口、產品缺陷）。「無法判定（上游 X）」的原因類別跟上游 X 相同。不改檢查讓它通過：判成文件漂移或工具缺口的照實記下，另開 PR 修。
3. 每個導覽的三態（CI 與人工檢查一起算）：任一條失敗 → 失敗；沒有失敗但有無法判定 → 無法判定；否則通過。

#### 人工檢查的共通規則

`page_checks.py` 實作了同一套規則；人工檢查照這裡做：

- 比對 API 字串與頁面文字前，兩邊都把空白正規化：換行（`\r`、`\n`）、全形空白（U+3000）、不換行空白（U+00A0）等 Unicode 空白與連續半形空白換成一個半形空白、去頭尾空白（瀏覽器的頁面文字會改寫空白）。tab 不動：表格列以 tab 分欄，檢查裡的 `\t` 就是 tab。
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

   - 程式：`task/227-verify-skill` @ `5fbf04c`（照 `summary.md` 開頭的「程式」行；有未 commit 的改動時註明照工作樹建置；G7 加註 `--g7`）
   - 副本：資料日 2026-10-21（`facts.json` 的 `market_latest_trading_date`），alembic `0016_group_score_archive`，複製 10.1 秒
   - 個股 E／S：TWSE 3004，今日榜 #1 族群「電機機械」的第一個成員（照 `summary.md` 開頭的「個股 E／S」行）
   - 證據：https://github.com/YiCheng0608/stock-lab/tree/pr-assets/227/20261022-0130
   - 人工檢查（獨立 session 判讀）：T10 通過；N7 失敗（id 2851 摘要多出原文沒有的營收數字）；N8 通過

   | 導覽 | 結果 | 失敗或無法判定的檢查（原因類別） |
   | --- | --- | --- |
   | 今日可買 `/` | 通過 | — |
   | 新聞 `/news` | 失敗 | N7：AI 摘要不忠於原文（產品缺陷） |
   | 族群 `/themes` | 失敗 | G2：族群榜缺資料日期標記（產品缺陷） |
   | 個股 `/stocks` | 通過 | — |
   | 觀察中 `/watch` | 無法判定 | A1：`/api/actions?limit=20` 回 500（產品缺陷） |
   ```

   範例的數值與結論是虛構的。
3. **推送**：分支名為 `task/<n>-...` 時 `bash "$WT/tools/ops/push_pr_assets.sh" --issue <n> --dir "$OUT"`（`.private/` 等隱藏項目不推；不要把輸出接到 `head`，會讓推送中斷），「證據」行就是它印出的第二行（`https://github.com/YiCheng0608/stock-lab/tree/pr-assets/<n>/<$OUT 的目錄名>`）。分支不是 `task/<n>-...` 時不推送，證據行寫 `$OUT` 的本機路徑。
4. 最後回覆：summary 全文。不自行在 Issue 或 PR 留言，由呼叫者決定貼到哪裡。

### 私人資料

私人模式（`facts.json` 的 `portfolio_positions` 大於 0）時，`page_checks.py` 的輸出整個寫到 `$OUT/.private/`（不推送），並 `mv "$OUT/copy.json" "$OUT/.private/"`。推送的 summary 改用 `page_checks.py` 同時寫出的 `status.md`（同樣的表格，只有每條檢查的結果，不含證據文字）：`cp "$OUT/.private/status.md" "$OUT/summary.md"`，再照[證據](#4-證據)第 2 步在前面加段落並註明「私人模式」。人工檢查樣本只有新聞與候選、沒有庫存，可以推送：`cp -r "$OUT/.private/manual" "$OUT/"`；人工檢查的證據寫樣本 id 與原句，不抄庫存行。

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
   . "$V/ports"; D="$(dirname "$DB")"; cd "$WT" || exit 1
   STOCK_DATA_DIR="$D" STOCK_DB_PATH="$DB" STOCK_RAW_DIR="$D/raw" \
     "$PY" -B -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" > "$V/logs/api.log" 2>&1 & echo $! > "$V/api.pid"; wait
   ```

   `cd` 要單獨一行：寫成 `cd ... && 程式 &` 時背景的是整個 `&&` 串成的子 shell，`$!` 是子 shell 的 PID，收尾 `kill` 只殺到子 shell，服務會留著。

4. **前端**（同樣背景執行；PID 寫進 `$V/web.pid`）：

   ```bash
   . "$V/ports"; cd "$WT/frontend" || exit 1
   VERIFY_DIST="$V/dist" VERIFY_WEB_PORT="$WEB_PORT" VERIFY_API_URL="http://127.0.0.1:$API_PORT" \
     node node_modules/vite/bin/vite.js preview --config "$WT/tools/verify/vite.preview.mjs" > "$V/logs/preview.log" 2>&1 & echo $! > "$V/web.pid"; wait
   ```

5. **等就緒**（最多約 60 秒，不用 `sleep`）：

   ```bash
   . "$V/ports"; for url in "http://127.0.0.1:$API_PORT/api/health" "http://127.0.0.1:$WEB_PORT/api/health"; do
     curl -fsS -o /dev/null --retry 60 --retry-delay 1 --retry-connrefused --retry-all-errors "$url" || echo "not ready: $url"; done
   ```

   有 `not ready` → `$V/logs/api.log` 出現 `Database is not ready` 就抄該行；五個導覽全部無法判定，跳到收尾。

## 收尾

只關本 skill 啟動的程序、只刪本 skill 的暫存。

**容器**：`set -a; . "$V/ports"; set +a; dc down --volumes --rmi all > "$V/logs/down.log" 2>&1` 刪掉 `$P` 的容器、網路、volume（含副本）與 image，再 `docker ps -a -q --filter "label=com.docker.compose.project=$P"` 與 `docker volume ls -q --filter "label=com.docker.compose.project=$P"` 確認兩個都沒有輸出；接著刪 `$V/ports`、`$V/gitfile` 與 `$V/stock.db`（各用一行 `rm -f` 寫完整路徑），再照下面第 3、4 步。

**本機**：

1. `kill $(cat "$V/api.pid") $(cat "$V/web.pid")`，再 `. "$V/ports"; curl -s -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:$API_PORT/api/health" "http://127.0.0.1:$WEB_PORT/api/health"` 確認兩個都印 `000`（連不上；程序約 1 秒後才結束，緊接著查可能還是 200，另起一個命令再查）；背景工作因此回報 failed 屬預期。再查還有回應就是服務沒關到，用 PowerShell `Get-NetTCPConnection -State Listen -LocalPort <埠>` 找出 `OwningProcess` 再 `Stop-Process`。之後刪 `$V/api.pid`、`$V/web.pid`、`$V/ports`。
2. 刪 `$V/dist`；CI 模式另刪 `$V/db`；真資料模式另刪 `$V/raw`（API 啟動時建的空目錄）與 `$V/stock.db`（含同名 `-wal`、`-shm`、`-journal`、`.partial`），各用一行 `rm -rf` 寫完整路徑。保留 `$V/out/`（證據）與 `$V/logs/`。
3. `ls -a "$OUT/shots"`（私人模式看 `$OUT/.private/shots`）不應有 `.browser-*`（`screenshot.cjs` 自己會刪；殘留就刪掉並記在 summary 最後一段「清理」）。
4. 不刪 `frontend/node_modules`（下次重用）；不碰 `.local/verify` 以外的路徑。
