# Review: spec-12（依賴清單擴充 — ddddocr + beautifulsoup4/lxml）

**Verdict: pass**

審查方式：focused（差異導向，實讀檔案內容 + 實驗依賴解析）。

## Upgrade Triggers 檢查清單

### 1. 增列以外動到 spec-2 已寫的既有依賴/build/metadata 區段（越界）

**✓ PASS**

- `[project].name`、`version`、`requires-python`、`description` 全部未動
- `[project].optional-dependencies.dev` 未動（`pytest-asyncio>=0.24` 仍在）
- `[build-system]` 未動（`requires = ["setuptools>=68"]`、`build-backend` 完全相同）
- `[tool.setuptools.packages.find]` 未動（`include = ["app*"]` 完全相同）
- spec-2 原有 9 個依賴**逐字未改**：
  - `fastapi>=0.115` ✓
  - `uvicorn[standard]>=0.32` ✓
  - `sqlalchemy>=2.0` ✓
  - `alembic>=1.13` ✓
  - `psycopg[binary]>=3.2` ✓
  - `apscheduler>=3.10` ✓
  - `httpx>=0.27` ✓
  - `pydantic-settings>=2.5` ✓
  - `pytest>=8.3` ✓

### 2. 三套件（ddddocr, beautifulsoup4, lxml）任一未增列

**✓ PASS**

實檢查依賴清單：

- `ddddocr` — **存在**（第 16 行，無版本約束）
- `beautifulsoup4` — **存在**（第 17 行，無版本約束）
- `lxml` — **存在**（第 18 行，無版本約束）

三者皆在 `[project].dependencies` 清單。版本約束採用寬鬆（無釘死版本號），符合 spec-12 worker 指示「版本約束用寬鬆下限或不釘死」。

### 3. 破壞既有依賴解析致安裝失敗

**✓ PASS**

實驗過程：

1. **TOML 語法驗證**：`python3 -c "import tomllib; tomllib.load(open('backend/pyproject.toml','rb'))"` — ✓ 成功解析，無格式錯誤
2. **pip 依賴解析**：`pip install --dry-run -e .` — ✓ exit 0，無版本衝突警告
   - 所有 spec-2 原有依賴解析成功、滿足版本約束
   - 三個新套件無版本約束衝突（寬鬆下限）
   - 依賴樹無循環或不相容情況
3. **導入驗證**：
   ```python
   import ddddocr      # ✓ 成功
   import bs4          # ✓ 成功（beautifulsoup4 import 名）
   import lxml         # ✓ 成功
   ```
   所有三個套件都能正常導入，無安裝失敗或導入錯誤。

### 4. Outputs 越界（改到 pyproject.toml 以外的檔案）

**✓ PASS**

實檢查 `allowed_outputs` 與實際改動：

- `allowed_outputs` 宣稱：`["backend/pyproject.toml"]`
- 實際改動檔案（非源碼層級）：僅 `backend/pyproject.toml`
- 無改動 forbid_outputs 內任何檔案：
  - ✓ 未改 `backend/Dockerfile`
  - ✓ 未改 `docker-compose.yml`
  - ✓ 未改 `backend/app/*` 任何目錄
  - ✓ 未改 `backend/alembic*`
  - ✓ 未新增測試檔（無 `*_test.py` / `*.test.*` / `backend/tests/*`）

## 完成定義檢查

spec-12 的完成定義要求：

1. ✓ `backend/pyproject.toml` 以 tomllib 解析成功
2. ✓ 依賴清單含 `ddddocr`、`beautifulsoup4`、`lxml`
3. ✓ spec-2 原有依賴與其他區段**原封未動**（diff 僅新增依賴行）
4. ✓ preflight 安裝後 `import ddddocr`、`import bs4`、`import lxml` 皆成功

## 結論

未發現需要 rework 的項目。

- **依賴寫入**：三套件（ddddocr、beautifulsoup4、lxml）正確增列
- **既有內容**：spec-2 的 9 個依賴、build/tool/metadata 區段、可選依賴全部維持原狀，未有誤改
- **依賴解析**：TOML 語法正確、pip 依賴樹無衝突、三個新套件導入無誤
- **Ownership 邊界**：僅改動 `allowed_outputs` 內的檔案，未越界

下游 spec-7（籌碼）、spec-8（分點）、spec-9（除權息）在本任務後可安心導入 `beautifulsoup4`/`lxml`/`ddddocr`，不會卡在「套件不存在」。
