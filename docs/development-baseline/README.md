# 開發與驗證入口

協作、資料選擇、保留例外及清理失敗的唯一規則見 [AGENTS](../../AGENTS.md#驗證資料與暫存)；接手狀態見[協作紀錄](../TASK_COORDINATION.md)。

## 版本與資料

使用 `git status --short`、`git diff`、`git log -1` 核對來源。`.gitattributes` 固定 LF，避免改變 replay 綁定的 source bytes。Git 保存測試程式與 fixture 建構方式，不備份本機 DB、raw、依賴或生成產物。

資料與落盤選擇依 [AGENTS](../../AGENTS.md#驗證資料與暫存)；磁碟驗收使用專案外最小隔離檔案，並遵守該測試的 snapshot 契約。

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

測試與清理結果、殘留預算及例外處理依 AGENTS，原始結果留 task。

## 歷史驗證

歷史測試不代表目前來源已驗收；原始數據依[文件索引](../README.md#歷史查閱)取閱，已刪除的 Temp 附件不作接手依賴。
