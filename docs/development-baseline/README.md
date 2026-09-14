# 開發與驗證入口

角色、驗收及索引／Git commit 流程查 [AGENTS](../../AGENTS.md)；驗證資料與暫存以 [AGENTS 的對應章節](../../AGENTS.md#驗證資料與暫存) 為唯一協作規則。當輪角色 ID 與暫停／接手狀態查 [協作紀錄](../TASK_COORDINATION.md)。

## 版本基準

以 Git 提交為原始碼基準，使用 `git status --short`、`git diff` 與 `git log -1` 核對。`.gitattributes` 固定 LF，避免 checkout 改變 pure-rule replay 所綁定的 domain.py bytes。

本機 DB、原始資料、備份、依賴與測試產物由 `.gitignore` 排除。Git 不備份正式或 `.local` 資料庫；文件或測試工作也不等於 migration、資料修復或正式資料庫寫入授權。

## 驗證資料怎麼選

依要證明的行為選最小資料形式，不為每次驗證複製整份資料庫。減少暫存不能縮小驗收條件；需要驗證磁碟行為時，記憶體資料不能取代隔離落盤。

| 要驗證的行為 | 優先資料 | 使用邊界 |
| --- | --- | --- |
| 一般只讀功能與整合查詢 | 已授權的實際資料；固定、少量、唯讀樣本可重用 | 記錄資料的來源版本／日期／範圍；接上實際資料前，先查入口、設定載入及 Python 模組 import 是否會建立目錄或寫 DB。唯讀授權不包含對正式 DB 建庫、寫入、migration、修復、資料匯入／收集，或啟動有寫入副作用的流程。 |
| 純計算、格式解析、特殊條件與 edge case | 記憶體資料或最小 fixture | 保留可重現的明確 assertions；不能用當下 live 資料取代 edge case。 |
| 檔案或磁碟 DB 寫入、備份、跨程序／重開、檔案雜湊、CLI 路徑 | 專案外的最小隔離檔案 | 只建立該行為必要的檔案，沿用既有隔離與 snapshot 契約；不得把正式資料庫或正式資料目錄當作隔離測試目標，也不得對其執行匯入或寫入。 |

測試程式與 fixture 建構方式留在 Git。實際命令、exit code、版本、結果與限制直接留在執行任務回覆；長期決策更新既有文件。不要建立各角色的 `external-review` 目錄，也不要為交接另存重複的結果、來源副本或 manifest。

## 後端驗證

依變更選擇必要驗證範圍。純文件工作以差異、連結與內容一致性核對為主；以下是在專案根目錄使用入口的示例，完整 backend 並非每次修改或每個角色都要重跑。

```powershell
# 啟動與 migration 邊界
& ./tools/Invoke-Validation.ps1

# 完整 backend 測試
& ./tools/Invoke-Validation.ps1 -TestPaths @('backend/tests')
```

入口優先選目前使用者的 bundled Python，否則使用 PATH 中的 python；也可用 `-PythonPath` 指定可執行檔。完整 replay 測試需要 CPython 3.12.14；不要為換環境而放寬規則的 runtime/source binding。

依賴來自 `backend/.deps`、`backend/.validation-deps` 或所選 Python 環境。重建環境使用 `backend/requirements.txt`；[驗證版本清單](validation-requirements.lock.txt) 記錄本機驗證過的版本，可作 pip constraints，並非附 wheel 雜湊的跨平台 lockfile。

### 現行入口的落盤行為

`tools/Invoke-Validation.ps1` 目前每次呼叫仍會在系統暫存區建立專案外的唯一目錄，並將 STOCK 路徑、TEMP、TMP 與 pytest basetemp 指向該處，以符合離線 snapshot 契約。`finally` 會還原呼叫端環境並嘗試清理；`-KeepArtifacts` 會跳過清理。入口尚未實作產物數量／大小額度的自動強制，因此不能宣稱驗證已全改為記憶體、完全不落盤或已有 quota enforcement。

預設不使用 `-KeepArtifacts`。只有具體且未解決的故障需要留下必要復現案例的最小證據時，才由統籌在原任務核定保留理由、確切範圍、期限或清理條件；不能只以一般除錯為由保留整套已成功的 full suite。不需逐次再問使用者，工具本身的審核仍照常適用。不要把保留物再複製進專案或另一個交接目錄。

每批必要落盤由統籌依測試規模設定並回報產物預算，明列產物及殘留各自的數量與大小上限。達上限時只暫緩新增落盤，其他可進行的工作繼續；必要測試若未執行，不得回報為通過。既有 snapshot reader 的隔離要求仍須遵守，不能為了少建暫存而改跑無隔離的正式資料匯入。

清理失敗與測試結果分開回報。只有保有 pytest 原始成功輸出或等價的明確成功證據時，才能把測試本身另行驗收；清理造成整體程序非零 exit 時，不得改報為 exit 0。記錄本次任務所擁有的確切路徑、數量、大小與失敗原因，後續驗證仍使用新的隔離目錄；不要因清理失敗重跑已通過的測試、卡住整輪等待使用者，或繞過工具拒絕。

## 歷史結果只供追溯

2026-09-14 曾移除 1,801 個封存／驗證檔案（1,540,143,603 bytes）；使用者亦曾移除最後的 `.local/temp-retention-work`。必要依賴保留，當時 backend 227 項定向測試曾在封存移除後通過。這些都是歷史結果，不能冒稱為目前任務重新執行或檔案現況。

歷史文件的 Temp／manifest 路徑只表示當時驗收背景，不再是接手依賴；不宣稱仍能完整還原已刪除的歷史附件。新驗收以當次實際執行與 Git 版本為準。

2026-09-14 文件／工具整理時曾驗證：完整 backend 2,405 passed、2 skipped（Windows symlink 權限）、12,414 warnings；前端 6 個測試檔及 TypeScript/Vite build 通過，build 有既有的大型 chunk 提示。當時也驗證過入口的成功／失敗清理、環境還原及路徑拒絕，以及 335 個本機 Markdown 連結；正式與 `.local` DB bytes 未變。引用這些數字時須附日期與原始任務背景，不可當作新一輪驗收證據。
