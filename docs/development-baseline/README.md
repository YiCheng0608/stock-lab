# 開發與驗證入口

R34 狀態及既有四個 task ID 統一維護於 [協作紀錄](../TASK_COORDINATION.md)。本次文件／工具整理及 Git commit 不代表恢復 ROADMAP 派工。

## 版本基準

整理後以 Git 提交為原始碼基準，使用 `git status --short`、`git diff` 與 `git log -1` 核對。舊 R33 的 166 檔案／mtime 清單只描述整理前狀態，已由 Git 取代，不再維護一份會隨正常修改失效的平行基準。`.gitattributes` 固定 LF，避免 checkout 改變 pure-rule replay 所綁定的 domain.py bytes。

本機 DB、原始資料、備份、依賴與測試產物由 `.gitignore` 排除。Git 不備份正式或 `.local` 資料庫；本次也沒有 migration 或資料修復。

2026-09-14 起，索引角色亦負責每輪及已授權獨立維護的本地 Git commit：統籌先驗收來源／文件並 freeze，索引更新及 coverage 經複核後，索引角色只提交核准路徑，回報 hash、提交檔案與剩餘差異。完整規則見 [AGENTS](../../AGENTS.md#2026-09-14-補正索引完成後必須封存-git-版本)；不再把只有索引 receipt、沒有 commit 或具名無差異證據的結果當成版本封存完成。

## 後端驗證

在專案根目錄執行：

```powershell
# 啟動與 migration 邊界
& ./tools/Invoke-Validation.ps1

# 完整 backend 測試
& ./tools/Invoke-Validation.ps1 -TestPaths @('backend/tests')
```

入口優先選目前使用者的 bundled Python，否則使用 PATH 中的 python；也可用 `-PythonPath` 指定可執行檔。完整 replay 測試需要 CPython 3.12.14；不要為換環境而放寬規則的 runtime/source binding。

依賴來自 `backend/.deps`、`backend/.validation-deps` 或所選 Python 環境。重建環境使用 `backend/requirements.txt`；[驗證版本清單](validation-requirements.lock.txt) 記錄本機驗證過的版本，可作 pip constraints，並非附 wheel 雜湊的跨平台 lockfile。

所有 STOCK 路徑、TEMP、TMP 都指向專案外新建的唯一測試目錄，以符合離線 snapshot 契約。成功或失敗後均清理該目錄並還原呼叫端環境；只有明確加上 `-KeepArtifacts` 才保留供除錯。不要把測試產物再轉存專案。

## 清理結果與歷史引用

2026-09-14 已移除 1,801 個封存／驗證檔案（1,540,143,603 bytes）；使用者亦已移除最後的 `.local/temp-retention-work`，本次檢查確認不存在。必要依賴保留，既有 backend 227 項定向測試曾在封存移除後通過。

歷史文件的 Temp／manifest 路徑只表示當時驗收背景，不再是接手依賴；不宣稱仍能完整還原已刪除的歷史附件。新驗收以當次實際執行與 Git 版本為準。

2026-09-14 文件／工具整理驗證：完整 backend 2,405 passed、2 skipped（Windows symlink 權限）、12,414 warnings；前端 6 個測試檔及 TypeScript/Vite build 通過，build 仍有既有的大型 chunk 提示。驗證入口的成功／失敗清理、環境還原及路徑拒絕另行通過；335 個本機 Markdown 連結有效。正式與 .local DB bytes 未變，產品演算法與資料契約未改寫。
