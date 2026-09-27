# 協作與接手狀態

本文件只留目前角色、接手與下一步；流程依 [AGENTS](../AGENTS.md)，能力與優先順序查 [ROADMAP](ROADMAP.md)。

## 目前狀態（2026-09-27）

- 上輪 R1-A2-P1-identity 的 TWSE TAIEX／TWII exchange identity 小批已有限 review 並 freeze；TPEx 同名 index 不增加已核實 session 分母、`taiex_rows` 或普通股票有效 bar 日。這不證逐欄／全市場 coverage、真實官方 session、歷史完整性或 PIT；邊界見 [TAIEX session identity](DATA_SOURCES.md#taiex-session-identity)。
- 本輪 R1-A2-P2 僅接受逐欄缺值／佔位資料路徑的唯讀盤點：legacy 缺 `TradeValue` 與合法零合流成 `turnover=0`、`TradeVolume` 小數截整；TAIEX close-only 的 O／H／L 及量額佔位仍可經特徵、API／圖表承接。`BarRecord`／`MarketBar`／upsert 無逐欄 unknown；flow consumer 可拒非正額但不能還原缺值。opt-in selected capture 的欄位 warning 與 run 級 partial／重試不等於 legacy 契約。詳見 [P2 資料路徑](DATA_SOURCES.md#r1-a2-p2-逐欄缺值與佔位資料路徑唯讀盤點)。
- 本輪程式白名單為空；未修改程式、未執行測試／DB／raw／live fetch。最小反例僅設計未執行，沒有新功能驗收；新增落盤產物配額為 0。A 整列拒收、B 逐欄 unknown 與 schema、C 暫不改程式均待使用者具名決定，等待不等於選 C。
- 上輪 R0-C4／B5b-core-1 及 R0-C2／B4b 純核心仍只在原有限 review 範圍內；完整 B5b／B4b／R0 未完成。R0-B2 的本地 selected-bar 證據 verifier 與 metadata 接線仍缺已授權可唯讀的完整 snapshot、配對 body／receipt、exact attempt／ordinal 與 registry pins tuple；依賴未變前保持待驗，不重複搜尋或建 specimen。R35–38 與獨立 UI 維護保留各自既有有限 review，歷史回算與 PIT 仍待驗。

### 角色與寫入分工

統籌已核對本輪四個新 task ID、共同專案目錄與接手；model／reasoning 採 [AGENTS](../AGENTS.md#四個角色) 核定配置。上輪 ID 由原 task 追溯。

| 角色 | task ID／model／reasoning | 寫入／驗收範圍 |
| --- | --- | --- |
| 統籌 | `01a0e1bc-fb4b-75f1-a076-b9239e65209d`；`gpt-6-astra`／`high` | 已接手並核定 P2 唯讀盤點邊界；本輪接收文件自檢後 review，後續等待使用者決策。 |
| 程式 | `01a0e1bc-fbf3-7351-9aed-918520f213e6`；`gpt-6-sol`／`ultra` | 唯讀核查來源、保存與 consumer；程式寫入白名單為空，未執行測試；不改規格、不自行結案。 |
| 文件 | `01a0e1bc-fcac-77c3-8f97-dbe1f84b17b3`；`gpt-6-sol`／`xhigh` | 僅更新 `DATA_SOURCES.md`、`ROADMAP_EXECUTION.md`、`TASK_COORDINATION.md`，交統籌 review；不改程式、不提交。 |
| 索引與 Git commit | `01a0e1bc-fd5e-7b12-8f54-46bd53f6f350`；`gpt-6-luna`／`medium` | 本輪待命，不刷新索引、不 stage／commit；不改來源。 |

## 接續範圍

1. 已完成及驗收邊界：R1-A2-P1-identity 的窄修正保留上輪有限 review；本輪 P2 僅完成逐欄資料路徑唯讀盤點，未修程式或新增測試證據。R1-A2 整體仍提案／未完成。既有 R0-C4／B5b-core-1、B2、B4b 成果仍各限原 review 範圍。
2. 尚缺項：A 整列拒收、B 擴大契約／schema 保留 OHLC 與 unknown、C 暫不修改均未選定；拒收不是官方 missing／zero 定義。R1-A2 仍缺官方行情／TAIEX／法人／融資的逐市場、標的、session 與欄位用途 coverage，及真實來源、availability／revision、歷史完整性、PIT 證據。B2 specimen／pins 依賴與完整 B5b 等 R0 接線缺口未變。
3. 下一步與依賴／完成條件：決策前維持程式不變，這不代表已選 C；等待使用者具名選 A／B／C。若選 A／B，再核定實作與驗證範圍及既存資料處置；選 C 則暫不修程式。其後仍需具名實際證據驗逐市場／逐欄 coverage，不以列數、日期或 fixture 替代。B2 缺 specimen 時保持待驗。角色不自行結案或啟動下一輪。
4. 本輪文件差異待統籌 review 與接受；統籌尚未授權索引刷新或 stage／commit，索引角色待命。本輪後續停在等待使用者決策，不以文件自檢宣告整體 R1-A2 完成。本輪無新測試檔。

## 歷史與維護

舊角色 ID、交付狀態、測試及 commit 證據由 [Git／原 task](README.md#歷史查閱) 追溯；舊分派不覆蓋 AGENTS，也不恢復已刪除附件或舊統籌派工權。更新本文件時替換目前狀態，不追加逐輪日誌。
