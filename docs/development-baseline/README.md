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

### M1-P3b 記憶體事件接線的驗收入口

本輪額外測試落盤配額為 0，不能直接套用上述會建立隔離目錄的入口；也須先辨識 pytest conftest、App 啟動與 import 的 DB／目錄副作用。純計算、selected／receipt 拒收與 API 投影優先以不載入 conftest 的記憶體 fixture 驗證；實際來源與產品操作另外具名核對，不能用 fixture 或記憶體 App bundle 代替 live／production 驗收。限制與既有殘留見[協作紀錄](../TASK_COORDINATION.md)。

server `STOCK_TWSE_EVENTS_MEMORY_CAPTURE=1` 明示啟用 `POST /api/stocks/{exchange}/{symbol}/official-events/capture?as_of=YYYY-MM-DD`，不需 body 參數；普通 GET／import 不抓外網，成功後只有 process 記憶體原件再用，不寫 DB／檔案。程式、原件／API 與具名桌面／窄版操作已有限接受；API／UI 契約與驗收邊界見[個股頁 §11](../STOCK_RESEARCH_PAGE.md#11-m1-p3bselected-官方事件總覽接線)。本輪靶向回歸、前端型別／SSR 與記憶體全 App bundle 通過，未跑完整 backend／production Vite build；驗收用 memory catalogue 不代表真行情或 DB 證據。測試命令、版本、exit、結果與限制留本輪 task，不另存產物或解除已有清理拒絕。

### M2-P1 官方事件關注清單的驗收入口

本批新增 `GET /api/focus/official-events?as_of=YYYY-MM-DD` 與首次明示 `POST /api/focus/official-events/capture?as_of=YYYY-MM-DD`，共用 P3b 的固定來源／啟用值／cache／鎖，程式與具名操作已有限 review。額外落盤配額仍為 0，不能直接載入會建立目錄的 conftest 或把隔離 memory catalogue 當真行情／正式 DB；純記憶體 consumer／API 邊界與一次真原件 58 列／API／桌面／窄版操作已分開接受。操作、未支援範圍及清理結果見[個股頁 §12](../STOCK_RESEARCH_PAGE.md#12-m2-p1官方事件關注清單接個股總覽)；後端必要記憶體回歸、前端型別／SSR／記憶體 bundle 通過，完整 backend／production Vite build 未跑，不因記憶體 bundle 成功稱通過。原件未保存、不能離線重播；命令／版本／exit／hash 與失敗／退修及最終收據只留本輪 task，無新增附件／暫存。

## 歷史驗證

歷史測試不代表目前來源已驗收；原始數據依[文件索引](../README.md#歷史查閱)取閱，已刪除的 Temp 附件不作接手依賴。
