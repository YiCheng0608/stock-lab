# 台股研究專案

以官方市場資料為基礎的台股盤後研究平台。目標是把新聞事件、近期熱門題材、個股籌碼與技術條件整理成可追溯的研究候選、進出場計畫與持倉風險，再持續驗證結果。

目前已有官方資料收集、歷史回補、族群評分、突破／回踩固定規則、行動摘要、持倉與技術回測。可信媒體／國際新聞、分點短線資金分析、完整交易計畫與 AI 預測仍待建置；現有訊號不是經驗證的 AI 勝率或報酬預測。

## 產品方向與狀態

第一版暫以「盤後研究、最早下一交易日執行、持有數天至數週」為設計假設；精確持有期間與風險參數尚待決定。現行 v1 追蹤窗口為 T+5／T+20。

- 主流程：事件 → 族群／題材 → 個股證據 → 交易條件 → 持倉與結果追蹤。
- 五個主入口：今日、新聞、族群、個股、行動。
- 個股判斷分開呈現公司品質、事件機會、交易位置與持倉風險。
- 未知、資料不足與條件未成立分開處理；不為了產生候選而補值。
- 現有日線價格是最近收盤；盤中即時交易、自動下單不在第一版範圍。

2026-09-11 靜態核對已發現新聞詳情、來源時間排序、壓縮行動卡、張／股輸入和 backfill 指令，故不再沿用舊文件的「全部未實作」；當次沒有啟動服務、驗證正式 DB 或重跑測試。ATR 定義、固定 confidence 與規則點位等已知缺口，見 [開發路線](docs/ROADMAP.md)。

Round27 另把目前 checkout 的 API 啟動改為唯讀 schema readiness gate，且已通過獨立啟動與完整 backend review；它不會自動建庫、migration 或 repair，也沒有重啟使用者既有服務。

Round32 新增一個明確 opt-in 的 Python library，可對兩個 caller-provided、專案外 rollback-mode SQLite snapshots 做 exact legacy／signal-artifact 描述性比較。它沒有 CLI、API、UI、worker 或預設 DB 接線，報告固定不可比較整體，也不代表 paired replay、PIT、B2／B7 或預設版本切換完成；使用前先讀 [Signal comparison 離線唯讀契約](docs/SIGNAL_COMPARISON.md)。

## 架構

| 部分 | 技術／職責 |
| --- | --- |
| frontend | React、TypeScript、Vite、React Query、ECharts；研究介面。 |
| backend/app | FastAPI、SQLAlchemy；API、固定規則、決策聚合與資料模型。 |
| backend/worker | 官方資料 adapter、收集／回補、分析、追蹤與回測。 |
| data | SQLite 與原始來源回應；保存來源、雜湊、時間與稽核。 |
| docs | 產品、資料、策略、UI、操作與歷史規格。 |

## 本機啟動

在專案根目錄，以隔離資料路徑啟動：

    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install -r backend/requirements.txt

    $env:STOCK_DATA_DIR = (Join-Path $PWD '.local/data')
    $env:STOCK_DB_PATH = (Join-Path $env:STOCK_DATA_DIR 'stock.db')
    $env:STOCK_RAW_DIR = (Join-Path $env:STOCK_DATA_DIR 'raw')
    $env:PYTHONPATH = (Join-Path $PWD 'backend')

    python -m worker.cli init-db
    python -m uvicorn app.main:app --reload --port 8000

`init-db` 是明確的 schema 建立／升級動作；先確認三個 `STOCK_*` 路徑、備份與授權，再只對預定資料庫執行。目前 checkout 的 Uvicorn lifespan 就 schema 而言只做有限的唯讀 readiness 檢查，資料庫不存在、版本／必要結構不合或不可讀時會拒絕啟動，並提示先在正確路徑執行 `init-db`。這不代表 API 全程唯讀：請求處理器與 worker 仍可能寫資料；載入設定也仍會建立已設定的 data／raw 目錄。

另一個終端：

    Set-Location frontend
    npm install
    npm run dev

前端 API 預設為 http://127.0.0.1:8000/api，可由 VITE_API_BASE 覆寫。程式中的預設資料路徑是 data/stock.db；未設定隔離環境時，不要直接執行初始化或收集。Round27 沒有重啟使用者既有服務，因此已在執行的 process 可能仍載入舊版啟動行為。

現有 CLI：init-db、collect、daily、backfill、analyze、evaluate、backtest。完整命令、限制及 schema 遷移說明見 [操作手冊](docs/OPERATIONS.md)。

## 文件

先看 [文件索引與保留決策](docs/README.md)，再看 [產品規格](docs/PRODUCT_SPEC.md) 與 [開發路線](docs/ROADMAP.md)。

目前 R34 暫停；角色、接手狀態與交付流程查 [專案協作規則](AGENTS.md) 及 [協作紀錄](docs/TASK_COORDINATION.md)。索引角色只維護索引與 coverage；Git commit 依使用者授權執行。

本機測試使用 [開發與驗證入口](docs/development-baseline/README.md)：`tools/Invoke-Validation.ps1` 會隔離資料並於結束後清理。舊 Temp 歸檔已移除；Git 保存原始碼與文件，本機資料、依賴及產物由 `.gitignore` 排除。

- [資料來源與歷史 coverage](docs/DATA_SOURCES.md)
- [新聞與事件規格](docs/NEWS_SPEC.md)
- [策略、交易計畫與 AI 驗證](docs/STRATEGIES.md)
- [UI 文案](docs/UI_COPY_SPEC.md)／[詞彙表](docs/GLOSSARY.md)
- [Canonical v1 基準](docs/V1_SPEC.md)
- [Signal artifact 持久化契約](docs/SIGNAL_ARTIFACTS.md)／[離線 exact comparison library](docs/SIGNAL_COMPARISON.md)

Phase 3／4 原文件原路徑封存，保留歷史證據；不再用來代表目前能力或全專案開發優先順序。歷史 P0 資料為 partial，不能由收集數量推論策略有效；詳細數據集中於 DATA_SOURCES。
