# 專案協作規則

專案執行任務時，先用 codebase-memory-mcp。先查索引及 coverage；沒有索引或指定路徑未追蹤、過時、解析不足時，才使用原生搜尋／直接讀取該來源。記錄需刷新的路徑，統一由當輪索引 task 在 round 結束前更新；不再逐段刷新。

若 App MCP 回報 `Transport closed`，Round03 已驗證可用相同引擎的 CLI 替代通道：`C:\Program Files\nodejs\node_modules\codebase-memory-mcp\bin\codebase-memory-mcp.exe cli --help`。依 CLI 說明呼叫相同的 graph／coverage／index tools；不要為恢復連線終止其他 App／MCP 程序或修改全域設定。索引刷新仍由當輪索引 task 負責，並分開回報 CLI 更新結果與 App 連線故障。

## 目前狀態（2026-09-14）

R34 仍依使用者指示暫停，四個已建立的角色 ID 見 [協作紀錄](docs/TASK_COORDINATION.md)。本次暫存清理、文件／驗證工具整理及 Git commit 是使用者明確授權的獨立維護，不恢復自動派工或建立下一輪。歷史 Temp 附件已清理；接手使用 [開發入口](docs/development-baseline/README.md)、現行測試與 Git 基準，不依舊交接指令找回已刪除的環境。

## 現行規則（2026-09-13，2026-09-14 補正）：每輪四角色、新統籌接棒

- 統籌分配任務與 review：`gpt-6-astra`（astra），reasoning `high`。
- 程式實作：`gpt-6-astra`（astra），reasoning `medium`。
- 文件編撰與邏輯整合：`gpt-5.6-sol`，reasoning `xhigh`。
- Codebase 索引與 Git commit：`gpt-5.6-luna`，reasoning `medium`；在每輪結束前更新索引、驗證 coverage，經統籌複核後提交本輪已驗收的來源／文件。不負責輪初 baseline 或中途段落刷新。

2026-09-13 使用者更新規則：每一 round 使用四個新的 task 對話，包含統籌、程式、文件與索引，依上述模型與 reasoning 建立；不 fork／繼續上一輪角色對話。當輪統籌完成本輪驗收、文件收斂與輪末索引複核後，建立下一輪四個新 task，將責任交給下一輪新統籌。統籌不再跨輪固定。同一輪內的修正、證據補充及輪末索引修正，可 follow-up 當輪 task。舊輪對話保留作歷史紀錄，不自行刪除或封存。

交接須列出下一輪四個 task ID、範圍與依賴、互不衝突的寫入範圍、本輪接受的成果與驗證證據、限制與待辦、freeze 狀態、索引結果，以及 commit hash／提交檔案／剩餘工作樹差異。新建的程式／文件／索引 task 等待新統籌分派；新統籌確認接手並核對四個 ID 後開始派工，避免重複建立角色。舊統籌交接後停止派工，只補充交接資訊。若 ROADMAP 已完成或剩餘工作均需外部變化／使用者決策，記錄狀態，不為交接而建立空轉輪次。

統籌負責界定本輪範圍、依賴、驗收及 review；有具體需要才增加角色。各輪 task ID 與狀態見 [協作紀錄](docs/TASK_COORDINATION.md)，產品優先順序以 [ROADMAP](docs/ROADMAP.md) 為準。

歷史交接身分見 [統籌交接摘要](docs/COORDINATOR_HANDOFF_2026-09-12.md)，各輪驗收背景集中於協作紀錄及領域契約；不據歷史斷點重開已存在的輪次。

2026-09-12 使用者授權自 Round 03 起依相同步驟持續逐輪推進，直到 ROADMAP 完成，不需每輪再詢問是否繼續。使用者確認外部服務範圍為「免費公開資料與本地測試」。可獨立進行的工程工作持續處理；需要個人決策、付費來源或實際前瞻觀測的項目照實保留待決／待驗證，不以 mock 或改寫驗收條件冒稱完成。跨輪由下一輪新統籌接棒；定時喚醒先查協作紀錄確認當輪統籌與交接狀態，已交接的舊統籌不得恢復派工。

每輪流程：當輪統籌分派 → 實作／文件交付 → 統籌檢查差異與驗證 → 必要修正 → 更新文件狀態並 freeze → 當輪索引 task 在 round 結束前更新涉及分區並確認 coverage → 統籌複核索引並核定提交檔案 → 索引 task 執行 Git commit、回報 receipt → 統籌核對 commit 與剩餘差異、接受本輪 → 建立下一輪四個新 task → 新統籌確認接手。索引後若有來源修正，須在結案前補刷受影響分區；最終索引與 commit receipt 保存在 task 回覆，避免為寫回 hash 造成刷新／提交循環。收到「完成」回覆不等於已通過 review；索引成功也不代表功能驗收通過。

### 2026-09-14 補正：索引完成後必須封存 Git 版本

使用者重申索引角色應在 codebase 索引更新後執行 Git commit；本條將該責任正式納入每輪收尾及已授權的獨立維護。這項本地 stage／commit 不需每輪另問使用者，仍須先取得統籌對具體成果及檔案清單的驗收。

- 統籌交付已驗收的完整 path 清單與 freeze 狀態；索引角色更新涉及分區、回報 coverage／解析限制，待統籌接受後才 stage／commit。根目錄尚未索引的文件直接核對來源，不以缺少 root index 跳過其提交。
- 提交前核對 `git status --short`、工作樹 diff、既有 staged diff 與 freeze；只明列 `git add -- <核准路徑>`，檢查 staged diff 與檔案清單後建立本地 commit。不得用 `git add .`／`git add -A` 混入其他角色或使用者未驗收的修改；遇到不明 staged 內容或 freeze 漂移，回報統籌釐清，不自行重置或丟棄修改。
- 正式／`.local` DB、raw、暫存、依賴、密鑰與已忽略的索引產物不強制入版；commit 不包含 push、歷史重寫或全域 Git 設定變更。
- receipt 必須包含 commit hash、parent、實際提交檔案、驗證／索引結果及剩餘 staged／unstaged／untracked 狀態。若核准範圍確實無差異，回報既有 HEAD 與檢查結果，不造空 commit；失敗則保持未完成並回報原因。
- 舊輪「禁止 Git mutation／stage／commit」只保留為歷史分派背景，不覆蓋本條對已驗收檔案的 stage／commit 責任。恢復 R34 時須把本條及具體交付責任傳給既有索引角色；本次規則補正不恢復 R34。

2026-09-12 使用者再次明確要求：各角色 task 必須將交付檔案、實際驗證證據、限制與 freeze 狀態回報現任統籌，由統籌 review 後決定接受並進入下一任務，或退回同 task 修正。角色不自行宣告本輪結案、不自行啟動下一任務；分派時需明寫此交付責任。

目前共用現有專案目錄，分派需明確指定互不衝突的寫入範圍。程式 task 不自行修改規格；文件 task 不改程式；索引 task 不改專案來源。保留既有修改與歷史資料。正式資料庫、資料採購、外部帳戶、自動交易不因一般開發分派而自動授權。
