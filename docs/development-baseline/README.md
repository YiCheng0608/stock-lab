# 開發與驗證入口

協作、資料選擇、保留例外及清理失敗的唯一規則見 [AGENTS](../../AGENTS.md#驗證資料與暫存)；接手狀態見[協作紀錄](../TASK_COORDINATION.md)。

## 版本與資料

使用 `git status --short`、`git diff`、`git log -1` 核對來源。`.gitattributes` 固定 LF，避免改變 replay 綁定的 source bytes。Git 保存測試程式與 fixture 建構方式，不備份本機 DB、raw、依賴或生成產物。

| 要驗證的行為 | 資料選擇 |
| --- | --- |
| 一般唯讀功能／查詢 | 已授權的實際資料或固定小型唯讀樣本；記錄來源版本、日期、範圍，先查設定／import 的建立目錄與寫入副作用。 |
| 純計算、解析、邊界案例 | 記憶體或最小 fixture，保留可重現 assertions；live 資料不取代邊界案例。 |
| 保存、備份、跨程序／重開、檔案雜湊等磁碟行為 | 最小專案外隔離檔案，遵守原 snapshot 契約；不可用正式 DB 當測試目標或用 memory 降低驗收條件。 |

## 後端驗證

依變更選必要範圍；純文件只核對差異、連結與內容。以下從專案根目錄執行，完整 backend 不是每次修改或每角色必跑：

```powershell
# 預設：啟動與 migration 邊界
& ./tools/Invoke-Validation.ps1

# 需要完整回歸時
& ./tools/Invoke-Validation.ps1 -TestPaths @('backend/tests')
```

入口優先使用目前使用者的 bundled Python，否則使用 PATH，也可傳 `-PythonPath`。完整 replay 需要 CPython 3.12.14，不得放寬 runtime/source binding。依賴來自 `backend/.deps`、`backend/.validation-deps` 或所選環境；重建依 `backend/requirements.txt`，[驗證版本清單](validation-requirements.lock.txt)可作 constraints，並非附 wheel hash 的跨平台 lockfile。

### 現行入口的落盤行為

每次呼叫仍會建立專案外唯一目錄，將三個 `STOCK_*`、`TEMP`／`TMP` 及 pytest basetemp 指向該處。`finally` 還原環境並嘗試清理；`-KeepArtifacts` 跳過清理，依 AGENTS 預設不得使用。入口尚無自動數量／大小限制，也尚未全部改成記憶體測試。

命令、原始測試結果、程序 exit 及清理結果直接留 task，不另存整套報告。清理非零 exit 不改報零；已有明確成功證據的測試可另行驗收，不因清理失敗重跑或阻塞整輪。殘留預算與例外處理由 AGENTS 管理。

## 歷史驗證

2026-09-14 的清理、2,405-pass backend 與前端檢查屬歷史紀錄，不是目前來源或資料狀態的新驗收。完整數據可用 `git show 69f62cf:docs/development-baseline/README.md` 取閱；已刪除的 Temp 附件不再是接手依賴。
