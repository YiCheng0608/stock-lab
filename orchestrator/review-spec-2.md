# Review: spec-2（專案骨架 ＋ Docker Compose）

**Verdict: pass**

審查方式：focused（差異導向，實讀 diff/檔案內容 ＋ 實跑驗證，非只信 handoff summary）。

## 1. 忠實度（對照 design.md §4/§5 與 spec-2 完成定義）

逐檔實讀，結論：與宣稱相符，且獨立重跑完成定義列出的三項驗證，全部通過：

- `docker compose config`：實跑 `docker compose config`，**exit code 0**，語法與服務定義（postgres/api/ingestion、build context、env、ports、depends_on、healthcheck、volumes）皆正確展開。
- `from app.main import app`：實跑，可正常匯入。
- FastAPI TestClient `GET /health`：實跑，回應 `200 {"status": "ok"}`。

檔案內容核對：

- `docker-compose.yml`：三服務（postgres/api/ingestion）齊備，皆為 `restart: unless-stopped`；`api`/`ingestion` 皆 `depends_on: postgres condition: service_healthy`；postgres 有 `pg_isready` healthcheck；`DATABASE_URL`／`env_file`（`./backend/.env`, `required: false`）走 env，符合 §5「env 驅動、Docker Compose 全進 compose」與「不假設本機已裝 PG」的 worker 指示。
- `backend/app/main.py`：FastAPI app、`lifespan` 內先呼叫 `get_settings()`（讓必填 env 缺漏在 boot 期就爆炸，優於延遲失敗）、`GET /health` 回 `{"status": "ok"}`，邏輯正確、無 side effect 風險。
- `backend/app/config.py`：`pydantic-settings` `BaseSettings`，含 `database_url`、`telegram_bot_token`/`telegram_chat_id`（對應 §8 通知）、`app_env`、`timezone`；`get_settings()` 用 `lru_cache` 做單例，符合「設定走 env」的要求。
- `backend/pyproject.toml`：依賴清單（fastapi、uvicorn、sqlalchemy、alembic、psycopg[binary]、apscheduler、httpx、pydantic-settings、pytest）與 spec-2 指示逐條相符。
- `backend/Dockerfile`：`python:3.12-slim` 基底、裝 `build-essential libpq-dev`、`pip install .`、`EXPOSE 8000`、`CMD uvicorn app.main:app`，邏輯正確可跑。
- `backend/.env.example`：涵蓋 `DATABASE_URL`、`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`、`APP_ENV`、`TIMEZONE`，且 `.env`／`.env.*` 已在 `.gitignore`（`!.env.example` 例外），不會誤將機密提交。

`docker-compose.yml` 的 `ingestion` service `command` 為 `["python", "-m", "app.ingestion.scheduler"]`，與 `orchestrator/intake-tasks.md` 中 spec-11 規劃的入口模組路徑（`app/ingestion/scheduler.py` → `python -m app.ingestion.scheduler`）**完全一致**，未來 spec-11 落地後可直接生效、不需回頭改 compose（spec-11 的 `forbid_outputs` 也明文禁止其碰 `docker-compose.yml`，兩邊互相印證）。

## 2. Ownership 邊界

實際用 `find` 核對整個 worktree 檔案樹（非只信 worker 自稱）：不存在任何 `backend/app/models/*`、`backend/app/adapters/*`、`backend/app/notifications/*`、`backend/app/ingestion/*`，也沒有任何 `*_test.py` / `*.test.*` / `backend/tests/*`。worker 只產出 `allowed_outputs` 清單內的 8 個檔案（`backend/README.md` 屬清單內但未建立，非必要項，不算違規）。

多出的 `backend/app/__pycache__/*`、`backend/stock_lab_backend.egg-info/*` 為驗證匯入/安裝時產生的建置副產物；`__pycache__/` 已在 `.gitignore` 覆蓋，不會誤入版控。`egg-info/` 未被 `.gitignore` 明列，但屬 `pip install -e`/build 產物、非源碼，建議之後補一條 `*.egg-info/` 進 `.gitignore`（非阻斷項，附帶提醒）。

`git status --short` 確認目前僅 `backend/`、`docker-compose.yml`、`orchestrator/` 三個未追蹤路徑，無越界寫入其他既有檔案（如 `docs/`、`README.md` 根層級皆未被觸碰）。

## 3. 下游可用性

- pyproject 依賴：`sqlalchemy`/`alembic`/`psycopg[binary]`（spec-3 用）、`apscheduler`（spec-11 用）、`httpx`（spec-6/7/8/9 抓取用）、`pydantic-settings`（已用）皆已備妥，spec-3 起可直接 `import` 使用，不會卡在「套件不存在」。
- ingestion service 的模組路徑與 spec-11 規劃入口一致（見上）。
- **提醒（非 spec-2 缺陷，但會卡下游，建議提報 orchestrator/intake 留意）**：`pyproject.toml` 目前只在 spec-2 的 `allowed_outputs` 內，後續任何 spec（如 spec-4/6/7/8/9）的 `allowed_outputs` 都未包含 `pyproject.toml`。而 spec-8 的 worker 指示明點名「驗證碼透過注入的 `CaptchaSolver`（**預設 ddddocr**）」，`ddddocr` 目前不在依賴清單、且 spec-8 依現有邊界無法自行加入 pyproject。分點/籌碼頁面解析若需要 HTML parser（如 `lxml`/`beautifulsoup4`）也有同樣的處境。這不影響 spec-2 本身的驗收（spec-2 依其指示的清單「等」字面完成，未被要求預先加入 ddddocr 等未來套件），但屬於 intake 的 ownership 分配缺口，建議在 spec-8 派工前由 orchestrator 決定：要嘛把 `pyproject.toml` 追加進 spec-8（及需要新依賴的其他 spec）的 `allowed_outputs`，要嘛另開一個小任務專門補依賴。

## 4. 實跑驗證結果彙總

環境有 docker 與 python3，皆已實跑（非跳過）：

| 檢查 | 指令 | 結果 |
|---|---|---|
| compose 語法/服務完整性 | `docker compose config` | exit 0，三服務／healthcheck／depends_on／volumes 皆正確展開 |
| app 可匯入 | `python3 -c "from app.main import app"` | 成功 |
| health endpoint | `TestClient(app).get("/health")` | `200 {"status": "ok"}` |

## 結論

未發現需要 rework 的項目。忠實度、ownership 邊界、下游可用性（除上述已標註為「非本任務缺陷」的依賴分配提醒外）皆通過查核。
