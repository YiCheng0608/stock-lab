# features

[`page_checks.py`](../../../../tools/verify/page_checks.py) 與人工檢查都依下表順序做五個檔。後面的檔案會用前面記下的值（今日 → 族群 → 個股 → 行動走同一條路徑），順序不可換；CI 只驗其中幾頁時，`page_checks.py` 自己向 API 取前面的值。同一頁內，負責某值的檢查（下表「負責的檢查」）先跑，結果仍依編號列出。

| 順序 | 檔案 | 導覽代號 | 記下供後面使用 |
| --- | --- | --- | --- |
| 1 | [today.md](today.md) | `today` | `D`、`B`、`today-board.json` 的 `items[0].theme_id`（`T`）與 `display_name` |
| 2 | [news.md](news.md) | `news` | — |
| 3 | [themes.md](themes.md) | `themes` | — |
| 4 | [stocks.md](stocks.md) | `stocks` | `I`、`stock.json` |
| 5 | [actions.md](actions.md) | `actions` | — |

## 跨檔傳遞的值

| 值 | 定義 | 負責的檢查（上游） | 使用的檔 |
| --- | --- | --- | --- |
| `D` | `dashboard.json` 的 `as_of` 前 10 字 | today T2 | stocks S3（導覽列的 `資料 <D>`）；news N7、N8 的抽樣日 |
| `B` | `today-board.json` 的 `meta.trading_date` | today T4 | today T5；themes（族群榜 `B` 指各榜自己的 `meta.trading_date`，與今日的 `B` 應同一天） |
| `T`、名稱 | `today-board.json` 的 `items[0].theme_id` 與 `display_name` | today T5 | themes 的 `theme-detail`／`theme-members` URL 與 G5～G7 |
| `E`、`S` | 見下方[選股](#選股) | — | stocks 的 API、截圖與 S1、S3～S9；actions 的 `action-detail` 與 A6、A7 |
| `I` | `facts-stock.json` 的 `instrument.latest_trading_date` | stocks S8 | stocks S3～S7 |

### 選股

`E`、`S` 依序取第一個有的來源，整次 run 只選一次；`summary.md` 開頭的「個股 E／S」寫明用了哪個來源、前面的來源為什麼略過：

1. 今日榜：`today-board.json` #1 族群（`T`）的 `theme-members.json` 第一個成員（今日 → 族群 → 個股的路徑）；
2. 明日候選：`candidates.json` 的 `items[0].instrument`；
3. 市場列表：`stocks.json`（`/stocks?page=1&page_size=30`）的 `items[0].instrument`。

三個都沒有時，需要特定個股的檢查（S3～S9、A6、A7）判「無法判定」並寫三個來源各缺什麼；不需要特定個股的 S1（只驗 `/stocks`）與 S2 照常判。

## 三態與上游

每條檢查的結果是 `通過`、`失敗` 或 `無法判定`，各頁的標題也是三態：任一條失敗 → 失敗；沒有失敗但有無法判定 → 無法判定；否則通過。無法判定不計入失敗。

- **無法判定**：API 非 200、截圖未 ready（含 `missingClicks`），或上游沒通過。
- **上游**：上表「負責的檢查」是該值的上游；另有同頁的先後關係（today T8 在 T7 之後、themes G3 在 G2 之後，兩者數的是同一批資料）。用到某值的檢查，在該值缺少或上游沒通過時判「無法判定（上游 X）」，原因寫上游的編號與結果。同一個缺陷只在上游記一次失敗，不在每一頁各記一次。
- **上游自己不判無法判定**：負責 `D`、`B`、`T` 的檢查在值缺少時改做[空狀態交叉核對](#空狀態交叉核對)：DB 有資料就是失敗，DB 也沒有才查空狀態文案。
- `page_checks.py --fixture`（CI）把無法判定也當成失敗：假資料庫每個值都在，無法判定代表工具或 API 壞了。

## 空狀態交叉核對

頁面顯示空狀態（「此榜目前沒有族群」、「當日零候選」、「目前沒有可顯示的行動摘要。」等）時，不只查文案：DB（`facts.json`）或另一支 API 有資料就判失敗，證據寫兩邊的值。涵蓋 today T2、T4、T5、T7、T9，themes G3，actions A4；actions A5（反向檢查）在頁面沒有任何行動卡時判無法判定，不判通過。

## 已知失敗

`page_checks.py` 的 `KNOWN_FAILURES` 以（頁、編號）為鍵，值是 Issue 連結與該缺陷的失敗訊息片段（`Known(issue, match)`）。失敗訊息含這個片段才算已知失敗（照報、不讓 run 失敗）；同一條檢查的其他失敗照常判失敗；已知失敗卻通過時 run 失敗，修好的 PR 同時移除該列。

## 檢查類型

各檔「檢查」表的 `類型` 欄：`CI` 是機械式檢查，[`tools/verify/page_checks.py`](../../../../tools/verify/page_checks.py) 有實作，CI `verify` job 每次在假資料庫上跑；`人工` 要 agent 判斷，抽樣規則寫死在 `page_checks.py` 的 `MANUAL`：每次 run 依規則取樣本寫到 `manual/<編號>.json`，`summary.md` 列出樣本數，判讀交給獨立 session（[SKILL 真資料模式](../SKILL.md#3-人工檢查與判讀)第 3 步），不自行挑樣本。新增或改類型時兩邊一起改，`backend/tests/test_verify_checks.py` 會擋下標 `CI` 卻沒實作、有實作卻沒標 `CI`、標 `人工` 卻沒有抽樣規則、或有抽樣規則卻沒標 `人工` 的檢查。

## 驗證範圍

CI `verify` job 先跑 [`tools/verify/verify_plan.py`](../../../../tools/verify/verify_plan.py)，依 PR 改到的檔案決定驗哪幾頁，只對那幾頁跑 `page_checks.py`；一頁都不用驗時 job 跳過其餘步驟並以 success 結束。規則只寫在本節與各 features 檔的「驗證範圍」，程式讀這些表，不另存一份。

每個改到的檔案由上往下比對下表，第一個符合的列決定範圍；`**` 跨目錄，`*` 不跨。沒有列到的路徑（`backend/` 其餘的程式與 schema、`backend/worker/`、`backend/alembic/`、`frontend/` 的建置設定等）一律全套。

| 路徑 | 範圍 | 理由 |
| --- | --- | --- |
| `tools/verify/**` | 全套 | verify 工具本身 |
| `.claude/skills/verify-stock-lab/**` | 全套 | features 檔、`db_facts.py` 與預覽設定 |
| `tools/ops/screenshot.cjs` | 全套 | 截圖工具 |
| `.github/workflows/ci.yml` | 全套 | `verify` job 本身 |
| `backend/app/api.py` | API route | 依改到的 route 對各頁「驗證範圍」；route 用到的函式、常數或 import 改了也算改到該 route |
| `frontend/src/**/*.test.ts` | 不驗 | 前端測試，不進 build |
| `frontend/src/**/*.test.tsx` | 不驗 | 前端測試，不進 build |
| `frontend/src/**/*.fixtures.ts` | 不驗 | 前端測試資料 |
| `frontend/src/**` | 前端檔 | 依各頁「驗證範圍」；沒列在任何頁的檔，取 import 它的檔所屬的頁 |
| `backend/tests/**` | 不驗 | 後端測試，由 `backend` job 跑 |
| `tools/ops/**` | 不驗 | 排程與維運腳本，不影響頁面；真資料模式用到的 `copy_db.py`、`push_pr_assets.sh` 在 gate 收尾實跑 |
| `tools/ci/**` | 不驗 | CI 檢查腳本，不影響頁面 |
| `docs/**` | 不驗 | 文件 |
| `**/*.md` | 不驗 | 文件 |
| `.github/**` | 不驗 | PR、Issue 模板與 `ci.yml` 以外的設定 |
| `.claude/**` | 不驗 | 其他 skill 與 hook 設定 |
| `.gitignore` | 不驗 | repo 設定 |
| `.git-blame-ignore-revs` | 不驗 | repo 設定 |
| `ruff.toml` | 不驗 | Python lint 設定 |

**樣式與共用元件跑全部檢查**：`styles.css`、`components/`、`App.tsx`、`types.ts` 等沒有列在任何頁的檔，被 `App.tsx` 或 `main.tsx` 直接 import（或沒有檔 import 它）時，五頁全部、全部檢查都跑，不只跑「頁面可用」類。理由：`DateBadge`、`Badge`、導覽列這些共用元件就是畫出資料日期、來源與「推論」標記的地方，日期與標記類檢查（T2、N3、G2、S3 等）正是在驗它們，只跑頁面可用會漏掉；全套在 CI 也只多幾分鐘。

### 不屬於五頁的 route

`backend/app/api.py` 的每個 route 都要列在某頁的「驗證範圍」或本表。`verify_plan.py` 每次先檢查：有 route 沒對到、表裡列了不存在的 route 或前端檔、前端檔清單少了 import 它的檔所屬的頁，就以 exit 2 結束（CI `verify` job 失敗）；`backend/tests/test_verify_plan.py` 對 `api.py` 做同樣的 route 檢查。

| route | 理由 |
| --- | --- |
| `GET /health` | 不屬於頁面；verify 啟動時就呼叫，後端測試涵蓋 |
| `GET /system/data-quality` | 系統資料頁，不在主導航 |
| `GET /glossary` | 名詞頁，不在主導航（頁內名詞說明用前端 `glossary.ts`） |
| `GET /groups` | 舊族群 API，前端未使用 |
| `GET /groups/{group_id}` | 舊族群 API，前端未使用 |
| `GET /instruments` | 舊標的 API，前端未使用 |
| `GET /instruments/{symbol}` | 舊標的 API，前端未使用 |
| `GET /signals` | 訊號 API，前端未使用 |
| `GET /signals/{signal_id}` | 訊號 API，前端未使用 |
| `GET /events` | 事件 API，前端未使用 |
| `GET /tracking` | 追蹤 API，前端未使用 |
| `GET /tracking/{signal_key}` | 追蹤 API，前端未使用 |
| `POST /portfolio` | 寫入庫存；verify 不送 POST |
| `DELETE /portfolio/{position_id}` | 刪除庫存；verify 不送 DELETE |
| `GET /data-quality` | 系統資料頁，不在主導航 |
| `GET /raw-payloads` | 系統資料頁，不在主導航 |
| `GET /ingestion-runs` | 系統資料頁，不在主導航 |
| `GET /backtest/summary` | 回測頁，不在主導航 |
| `GET /backfill-runs` | 回補覆蓋頁，不在主導航 |
| `GET /backfill-runs/{run_id}` | 回補覆蓋頁，不在主導航 |
| `GET /coverage` | 回補覆蓋頁，不在主導航 |
| `GET /strategies` | 系統資料與策略頁，不在主導航 |

## 結果表

每個 `results/<導覽代號>.md` 的表格都是四欄：`檢查`、`結果`、`原因類別`、`證據`。通過的檢查原因類別寫 `—`。

### 原因類別

失敗與無法判定的檢查各選一類：

| 類別 | 什麼時候用 |
| --- | --- |
| 文件漂移 | features 檔與現行程式不符（元件位置、文案、分頁、API 欄位改了），頁面照現行規格運作 |
| 工具缺口 | 證據取不到或取錯（`screenshot.cjs`、`curl`、`db_facts.py`、環境），不代表頁面錯 |
| 產品缺陷 | 頁面與 API／DB 不一致，或違反[顯示原則](../../../../docs/ROADMAP.md#v1-範圍基線2026-10-17-核定) |

**不改檢查讓它通過**：跑 verify 的同一輪不改 features 檔或工具。判成文件漂移或工具缺口的照實記下，另開 PR 修；修的時候以程式與規格為準，不以這次的頁面輸出為準。

## 陷阱

全部導覽共通的規則在 [SKILL 人工檢查的共通規則](../SKILL.md#人工檢查的共通規則)；只屬於某一頁的陷阱寫在該檔的「陷阱」小節。
