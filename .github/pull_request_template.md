Closes #<issue>

<!-- 分流見 docs/GITHUB_WORKFLOW.md「分流」。第 3 類（文件、流程檔、tools/ci/、純測試）沒有 Issue 時刪掉上一行，AC 區改寫「無 Issue，驗證見 CI」。CI 的 pr 檢查會讀本文。 -->

## 做了什麼

## 怎麼驗證

- [ ] 後端 pytest／ruff
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

## 未做／已知限制
