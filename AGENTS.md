<!-- owns: 協作角色、任務生命週期、並行上限、工程原則、文件原則、上下文壓縮保留、流程變更 -->
# 專案協作規則

本文管角色與原則；操作與欄位見[工作手冊](docs/WORKFLOW.md)，模板見 [docs/templates](docs/templates/README.md)；統籌的開啟、換手與無人值守見 [COORDINATOR](docs/COORDINATOR.md)；會擋下違規的檢查見 [GUARDRAILS](docs/GUARDRAILS.md)；產品方向與版本範圍見[ROADMAP](docs/ROADMAP.md)；前端視覺見[設計規範](docs/DESIGN_SYSTEM.md)。

## 目標

用最少的角色與步驟推進 ROADMAP 與 GitHub milestone 上的現行工作（V1 已完成，見 [ROADMAP](docs/ROADMAP.md#v1-已完成)）：每個任務一個 Issue、一個 worktree、一個 PR，CI 通過並經 review 後合併。流程服務產品，不反過來。

## 工具

- **GitHub Issues** 是任務來源：目標、範圍、驗收條件（AC）、決策與結果都記在 Issue。Project 看板只顯示狀態，不另建表。
- **Repo** 保存程式、文件、可重建測試。一次性命令、實測紀錄、待辦留 Issue。
- **Orca** 管 worktree 與 terminal；每個任務在自己的 worktree 工作，不在管理 checkout（`master`）改檔。排程只從獨立的發佈 checkout 執行，正式資料目錄在 repo 外（[排程](docs/ops/SCHEDULING.md)）；agent 不得在任何 checkout 跑 `git clean -x`，不得刪資料目錄。
- **codebase-memory** 先查索引再讀原檔；MCP 斷線改用同引擎 CLI，不重建整份索引。
- 回覆使用者一律繁體中文、台灣用語；程式、指令、路徑維持原樣。

## 角色

| 角色 | 預設模型／effort | 做什麼 |
| --- | --- | --- |
| 統籌 | `claude-fable-5-2`／`medium`，`--autocompact 400k` | 同時只有一個，一律由 agent 依 [COORDINATOR](docs/COORDINATOR.md#統籌-session)以 Orca 開啟：現任統籌自行換手；沒有統籌時使用者對任一 Claude session 說「開統籌」，由它開。拆任務、建 Issue、派工、review、合併、更新 ROADMAP 與文件、回報進度；使用者不在時依[無人值守運作](docs/COORDINATOR.md#無人值守運作)持續推進。 |
| 工程師 | `claude-opus-5-5`／`medium` | 每個任務一個 session，在自己的 worktree 實作、自測、寫文件、開 PR、處理 review 與 CI。 |

- 不設常駐 QA、文件、索引／Git 角色。需要獨立驗證時由統籌在 PR 上跑 `/code-review` 或另開一個 review session，見[工作手冊](docs/WORKFLOW.md#review-與合併)。
- 統籌可以自己當工程師做小任務；大任務或可並行的任務派給工程師 session。
- 使用者只決定產品取捨：範圍、來源與付費、刪除資料、部署、對外操作。其餘由統籌自行推進，不逐步請示。

## 任務生命週期

1. **建 Issue**：目標、範圍與不做事項、3～5 條可驗收的 AC、依賴、對應里程碑與依據；套對應的 milestone。要不要建 Issue 依工作手冊的[分流](docs/WORKFLOW.md#分流)。
2. **開 worktree**：以 Orca 從最新 `origin/master` 建 `task/<issue>-<slug>`，啟動工程師 session 並送任務全文。
3. **實作與自測**：工程師在 worktree 完成程式、測試與文件；跑改動相關的後端測試檔與 `ruff`（全套後端 `pytest` 由 PR CI 跑）、前端測試與 build（見[工作手冊](docs/WORKFLOW.md#本機檢查)）。
4. **PR**：描述做了什麼、怎麼驗、未做什麼；`Closes #<issue>`。CI 必須綠。
5. **Review 與合併**：統籌 review（必要時獨立 review），以 merge commit 合併；不 squash／rebase、不直接 push master。
6. **結案**：合併後 master CI 綠即關 Issue、移除 worktree；遠端 branch 由 GitHub 自動刪。master CI 紅就先修，不開新功能。

並行以不互改同一組檔案為原則，同時進行的任務以 3 個為上限（並行名額，統籌有空額就派下一張）；「做完、只等合併」的任務（PR CI 綠、review 完、工程師不再改）不算在內（使用者 2026-10-26 決定）；只剩等外部時點的實測或抽樣、工程師不再改程式的任務也不算（使用者 2026-11-09 決定，#1 [6728938283](https://github.com/YiCheng0608/stock-lab/issues/1#issuecomment-6728938283)）。衝突由後合併者在自己的 branch 解決，不全選一方。

## 工程原則

- **資料**：只用免費公開來源；每筆保存來源與資料日期；缺資料留空並標無資料，不補零、不混來源。DB、raw、金鑰、私人資料不進 Git。
- **顯示**：有資料就顯示並標來源與日期；LLM 產出與來源事實分欄並標「推論」。詳見 [ROADMAP 顯示原則](docs/ROADMAP.md#v1-範圍基線2026-10-17-核定)。
- **LLM**：只做新聞摘要、關聯、方向判讀與進出點說明；以本機 Claude Code 無介面模式（`claude -p`）用使用者的訂閱帳號呼叫，不接 API 金鑰、不計費；每次呼叫記模型與提示版本。
- **測試**：單元與計算用小 fixture 或記憶體 DB；需要磁碟時用隔離暫存檔並在測試後清理；真實資料驗收記日期與範圍。
- **不做**：自動下單、盤中即時、付費來源、未驗證勝率。部署、正式 DB、外部帳戶需使用者同意。
- **AC 不自行降低**：做不到就在 Issue 說明並請統籌決定拆分或延後。

## 前端

所有前端工作遵守 [DESIGN_SYSTEM](docs/DESIGN_SYSTEM.md)：token、字體、元件、圖表與狀態的視覺規則都以該文件為準，不在元件內寫死色碼；PR 附桌面與手機截圖。要偏離先在 Issue 說明並經統籌同意，同意後先改 DESIGN_SYSTEM 再實作。

## 文件

- ROADMAP 寫方向與版本範圍，[CAPABILITIES](docs/CAPABILITIES.md) 寫已完成能力；規格文件（PRODUCT_SPEC、`docs/spec/`、NEWS_SPEC 等）只寫確定的契約；過程與待辦留 Issue。
- 功能完成的同一個 PR 更新受影響文件；內容失效時同批刪除指向它的連結。
- 同一規則只寫一次，其他處放連結。

## 規則與強制手段

會擋下違規的檢查列在 [GUARDRAILS](docs/GUARDRAILS.md)；新增檢查時同一個 PR 在該表補一列。

## 上下文壓縮時保留

任何 session 被壓縮時，摘要必須保留：手上任務的 Issue／PR 編號與目前步驟；使用者最近的決策與其 #1 留言 id；等待中的事件（CI、回報、回補）與對應 terminal／worktree；已承諾未做完的事；使用者給過的參考資料（連結、檔案）與它們代表什麼；自己的 session id 與 terminal handle；事件佇列處理到哪個 seq、為定時承諾排的一次性工作是否仍在；心跳檔與壓縮計數檔的位置。不保留已結案任務的細節，那些在 GitHub。

## 流程變更

改本文、[WORKFLOW](docs/WORKFLOW.md) 或 [COORDINATOR](docs/COORDINATOR.md) 由統籌開 PR，使用者同意後合併；不占任務名額。
