# 協作與接手狀態

本文件只留目前角色、接手與下一步；流程依 [AGENTS](../AGENTS.md)，能力與優先順序查 [ROADMAP](ROADMAP.md)。

## 目前狀態（2026-09-27）

- 上輪 R1-A2-P1-identity 的 TWSE TAIEX／TWII exchange identity 小批已有限 review 並 freeze；TPEx 同名 index 不增加已核實 session 分母、`taiex_rows` 或普通股票有效 bar 日。這不證逐欄／全市場 coverage、真實官方 session、歷史完整性或 PIT；邊界見 [TAIEX session identity](DATA_SOURCES.md#taiex-session-identity)。
- 使用者已選定 R1-A2-P2+ 成交額缺值政策，原 A／B／C 待選狀態結束。TWSE `TradeValue`／TPEx `TransactionAmount` 缺失或無效時保留有效 OHLC／volume，以 `turnover=0` 及 `unavailable/missing` 或 `unavailable/invalid` 保存；來源明確零為 `available`。opt-in selected capture 同樣處理，TAIEX 合成額為 `unavailable/synthetic_index`。舊正值保留 `available`；舊零為 `unknown/legacy_zero_ambiguous`，負值／NULL 為 `unknown/legacy_invalid`；已有 status 的 migration 重跑不覆寫。API／TS 傳 status 與 nullable reason，兩種法人 flow ratio 遇非 available 關閉。精確範圍見 [P2+ 資料契約](DATA_SOURCES.md#r1-a2-p2-成交金額可得狀態有限接受)。
- 統籌已有限接受程式差異及六份文件；本文記錄截至正式 freeze 宣告前的 freeze-ready checkpoint，本次狀態措辭待統籌複核。純記憶體最後單次總計 66 passed（含群組身份 25 cases），`tsc --noEmit` 與 diff-check 通過；不同分批結果不相加。磁碟 selected capture／legacy migration 測試與正式 DB 升級待驗；未新增落盤測試產物，新增產物配額維持 0。未擷取官方 payload，未驗真實逐欄 coverage、PIT、TAIEX 合成 OHLC／volume 或 legacy 成交量小數截整。
- 上輪 R0-C4／B5b-core-1 及 R0-C2／B4b 純核心仍只在原有限 review 範圍內；完整 B5b／B4b／R0 未完成。R0-B2 的本地 selected-bar 證據 verifier 與 metadata 接線仍缺已授權可唯讀的完整 snapshot、配對 body／receipt、exact attempt／ordinal 與 registry pins tuple；依賴未變前保持待驗，不重複搜尋或建 specimen。R35–38 與獨立 UI 維護保留各自既有有限 review，歷史回算與 PIT 仍待驗。

### 角色與寫入分工

統籌已核對本輪四個新 task ID、共同專案目錄與接手；model／reasoning 採 [AGENTS](../AGENTS.md#四個角色) 核定配置。上輪 ID 由原 task 追溯。

| 角色 | task ID／model／reasoning | 寫入／驗收範圍 |
| --- | --- | --- |
| 統籌 | `01a0e228-009a-7672-b04c-22adc1a97f30`；`gpt-6-astra`／`high` | 已接手並有限接受 P2+ 程式範圍及六份文件；待複核本次狀態措辭、正式宣告 freeze，再複核索引與提交範圍。 |
| 程式 | `01a0e22b-b9a5-7211-8612-6af7f19601d4`；`gpt-6-sol`／`ultra` | 僅在統籌核定的程式／測試白名單實作與純記憶體驗證；已交付 freeze-ready 程式差異，不自行結案。 |
| 文件 | `01a0e22b-baa4-7781-8b12-cf50c6c64110`；`gpt-6-sol`／`xhigh` | 六份文件已獲統籌接受；本次只修正 `TASK_COORDINATION.md` 的 checkpoint 狀態，交統籌複核；不改程式或提交。 |
| 索引與 Git commit | `01a0e22b-bba8-7693-94d7-0472c357c3d2`；`gpt-6-luna`／`medium` | 待統籌正式宣告 freeze 後更新索引與 coverage；再待統籌核定提交範圍才 stage／commit；目前索引／commit 未授權，不改來源。 |

## 接續範圍

1. 已完成及驗收邊界：R1-A2-P1-identity 窄修正保留上輪有限 review；本輪 P2+ 成交額 availability 程式差異已獲有限接受，含 legacy TWSE／TPEx parser、selected capture、TAIEX 合成狀態、schema／fallback migration、API／TS 與兩種 flow ratio。驗證只限純記憶體與靜態檢查；R1-A2 整體仍提案／未完成。既有 R0-C4／B5b-core-1、B2、B4b 各限原 review 範圍。
2. 尚缺項：磁碟 capture／legacy migration 測試、正式 DB 升級與既存資料核對未做；R1-A2 的官方行情／TAIEX／法人／融資逐市場、標的、session、欄位用途 coverage，及 availability／revision、歷史完整性、PIT 證據仍缺。成交量小數截整及 TAIEX 合成 OHLC／volume 的用途風險未修。B2 specimen／pins 依賴與完整 B5b 等 R0 接線缺口未變。
3. 下一步與依賴／完成條件：統籌複核本次狀態措辭後正式宣告 freeze，索引角色輪末刷新涉及分區、驗 coverage；統籌複核後核定精確檔案清單，再由索引角色本地 commit。後續磁碟／正式 DB 驗證依既有授權與落盤限制另行安排，逐欄 coverage 須具名真實證據，不以列數、日期或 fixture 替代。B2 缺 specimen 時保持待驗。角色不自行結案或啟動下一輪。
4. 本文是正式 freeze 宣告前的 freeze-ready checkpoint；目前尚未 freeze、未刷新索引，索引／stage／commit 仍未授權。六份文件已獲接受不代表整體 R1-A2 完成；最終 freeze／索引／commit receipt 留原 task，依實際結果更新本節狀態。

## 歷史與維護

舊角色 ID、交付狀態、測試及 commit 證據由 [Git／原 task](README.md#歷史查閱) 追溯；舊分派不覆蓋 AGENTS，也不恢復已刪除附件或舊統籌派工權。更新本文件時替換目前狀態，不追加逐輪日誌。
