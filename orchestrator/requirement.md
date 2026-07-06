# 需求：stock-lab 第一期 Ingestion Pipeline

## 使用者原話

> 請幫我看一下 stock-lab 這個folder，並且根據docs/design.md開始第一期的ingestion pipeline的動工吧

## 範圍界定（依 docs/design.md 展開，供 intake 拆解與 reviewer 對照）

設計文件唯一事實來源：`docs/design.md`（本 worktree 內路徑相同）。本次只動工 design.md §6「第一期」項目 1「Ingestion pipeline」，具體範圍：

- 資料源涵蓋 §3 表列的四類：日價量（K 線）、籌碼（三大法人/融資券/借券）、券商分點（買賣日報表，含 §3 分點注意事項：只能抓當日、需節流、需處理驗證碼）、除權息/股本/基本資料。
- 每個資料源都是獨立 adapter（§2 原則 1：資料層與應用層分離），券商分點來源需預留未來替換為 FinMind 付費方案的 adapter 介面（如 design.md 提到的 `BrokerBranchSource`）。
- 技術棧依 §4：後端 Python + FastAPI，PostgreSQL 單庫（分點表按月分區＋(股票,分點,日期)索引）。
- 排程依 §5：APScheduler，不依賴 Windows 工作排程器；每日傍晚起每小時重試直到成功；ingestion 失敗當天要有失敗通知（§8 Telegram，可先做成 adapter + 最小可用實作或明確 stub，通知本身非本期重點但介面要留）。
- 價格處理依 §7：資料庫需同時存原始價與除權息還原價（還原係數自算），此為 ingestion 階段就要落地的資料模型。
- 使用者概念依 §2 原則 2：即使目前只有一筆 user，schema 設計不可寫死單一使用者。
- 部署依 §5：Docker Compose（Postgres + FastAPI + ingestion service），環境要能在 Mac 開發、之後可搬到 Windows WSL2。

## 明確排除（避免 intake 誤拆進來）

- K 線視覺化頁面、技術指標計算、篩選引擎、分點功能 UI、策略掃描、Telegram 實際推播內容、React 前端 — 這些是 design.md §6 第一期第 2 項以後或更晚，本次只做 ingestion pipeline（資料擷取、清洗、入庫、排程、失敗告警的介面）。
- 回測框架、分點異常掃描、code 逃生口 — 明確是第二期（§6）。
- 多租戶/權限/計費 — 明確不做（§2、§6）。
