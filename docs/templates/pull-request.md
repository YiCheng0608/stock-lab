<!-- owns: PR 模板 -->
<!-- 用法見 [模板清單](README.md)。複製本檔（含 HTML 註解）當 PR 本文再填；`gh pr create --body-file` 不會自動帶入。 -->
Closes #<issue>

<!-- 分流見 docs/WORKFLOW.md「分流」。第 3 類（文件、流程檔、tools/ci/、純測試）沒有 Issue 時刪掉上一行，AC 區改寫「無 Issue，驗證見 CI」。CI 的 pr 檢查會讀本文。 -->

## 做了什麼

## 怎麼驗證

- [ ] 後端：本機跑的測試檔（列出檔名；全套由 CI `backend` job 跑）／ruff
- [ ] 前端 test／build
- [ ] AC 逐條結果：
  <!-- 每條一行：AC-<n>：命令或查詢／輸出或連結／資料日期（沒有真實資料寫「無」）。只寫「通過」不算。 -->
  - AC-1：
  - AC-2：
  - AC-3：
- [ ] 前端變更附桌面與手機截圖，符合 docs/DESIGN_SYSTEM.md

## 欄位

- 高風險類別（有／無）：<!-- 有：列出碰到的 tools/ci/checks.py HIGH_RISK_PATHS 路徑，並加 independent-review label -->
- 更新的文件：
- worktree 外暫存目錄路徑：<!-- 沒有寫「無」；結案時統籌依此刪除 -->
- 會過期的記憶：<!-- 沒有寫「無」。本任務讓哪幾則 Claude Code 記憶過期（檔案刪除、流程改變、角色改名、坑已編成檢查），每則寫檔名與該怎麼改（改寫成什麼、併入哪則或刪除）；工程師不改記憶，統籌結案時照這裡改（docs/COORDINATOR.md「記憶」） -->

## 未做／已知限制
