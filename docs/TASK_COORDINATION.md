# 協作與接手狀態

本文件只留目前角色、接手與下一步；流程依 [AGENTS](../AGENTS.md)，能力與優先順序查 [ROADMAP](ROADMAP.md)。

## 舊 P2+ 輪：尚未結案，維持原限制

- R1-A2-P1-identity 已有限 review 並 freeze；邊界見 [TAIEX session identity](DATA_SOURCES.md#taiex-session-identity)。P2+ 成交額缺值政策已選定並有限接受，原 A／B／C 待選狀態結束；唯一詳細契約見 [DATA_SOURCES](DATA_SOURCES.md#r1-a2-p2-成交金額可得狀態有限接受)。
- 舊統籌已接手並有限接受 P2+ 程式補強，以及實際落盤的離線 fixture 缺額／明確零 capture→SQLite→API 路徑；這不是官方真實樣本驗收。legacy 磁碟 migration、其他 selected invalid／拒收的磁碟整合、正式 DB 升級及真實 coverage／PIT 仍待驗，詳見上述契約；R1-A2 整體未完成。
- R0-C4／B5b-core-1、R0-C2／B4b、R35–38 與獨立 UI 維護各保留原有限 review。完整 B5b／B4b／R0、歷史回算及 PIT 未完成。B2 仍缺已授權唯讀的完整 snapshot／body／receipt、exact attempt／ordinal 與 registry pins tuple；依賴未變前保持待驗，不重複搜尋或建 specimen。

### 舊輪 roster 與接續邊界

以下是尚未結案舊輪的接手依據；共同 repo 為 `C:\Users\YiCheng\Desktop\taiwan-stock-research`，基線 `ed89c50464720b6b277b731ca213fba8e42f5327`。model／reasoning 是各 task 建立時實際採用值，[AGENTS](../AGENTS.md#四個角色) 的新預設不回溯改寫。

| 角色 | task ID／model／reasoning | 寫入／驗收範圍 |
| --- | --- | --- |
| 統籌 | `01a0e26d-29a7-7c31-b292-3b903602ea51`；`gpt-6-astra`／`high` | 已接手並有限接受 P2+ 程式補強及單節點落盤 fixture 驗收；原紀錄停在四份文件待複核、正式 freeze 前。 |
| 程式 | `01a0e26d-2a6d-79d3-9361-6d743ac65b33`；`gpt-6-sol`／`ultra` | 核定測試白名單的差異已交付；指定測試由舊統籌執行並驗收，不自行結案。 |
| 文件 | `01a0e26d-2bfc-7f31-9524-690b7b6b04f2`；`gpt-6-sol`／`xhigh` | 舊輪四份文件交統籌複核，不改程式或提交。 |
| 索引與 Git commit | `01a0e26d-2b3e-7f22-aebe-51946822895c`；`gpt-6-luna`／`medium` | 舊輪正式 freeze 後才依原分派刷新與驗 coverage；該輪不 stage／commit／push，不改來源。 |

1. 已完成及驗收邊界：以 [P2+ 契約](DATA_SOURCES.md#r1-a2-p2-成交金額可得狀態有限接受) 的具名範圍為準；fixture 路徑不升格為全市場、真實來源或整體 R1-A2 完成。
2. 尚缺項：R1-A2 的逐市場、標的、session、欄位用途 coverage 及 availability／revision／歷史／PIT；成交量小數截整與 TAIEX 合成欄位用途風險未修。其餘 R0 接線與 B2 specimen／pins 缺口不變。
3. 下一步與完成條件：舊輪仍在正式 freeze 前；原後續為文件複核、freeze、輪末索引 coverage 驗證，尚無完成 receipt。來源／磁碟工作依原授權與配額另行安排，不以列數或 fixture 替代真實證據。
4. 舊輪配額 **1 根／10 MiB／200 entries** 只適用原指定測試節點；未擴大其他磁碟工作授權。使用者對舊輪的 **禁止 stage／commit／push／派下一輪** 仍有效；本次獨立維護不替舊輪宣告完成，也不恢復其派工。

## 2026-10-03 本次獨立文件維護

使用者授權修正 review findings 並落盤產品 flow，範圍只有文件；本次不新增程式角色。共同 repo 與基線同上，既有 `backend/tests/test_stock_day_capture.py` 差異保留且不納入本次提交。產品里程碑與後續依賴由 [ROADMAP](ROADMAP.md#接下來的順序近期產品里程碑) 及[執行清單](ROADMAP_EXECUTION.md#21-近期里程碑接線映射)負責，規劃不算能力驗收。

| 角色 | 本次 ID／實際建立參數 | 寫入／驗收範圍 |
| --- | --- | --- |
| 統籌 | session `01a0fde3-6be4-77a2-b86e-e033f8d7fd3a`；runtime 未提供可核實的 model／reasoning | 核定範圍、review、freeze、索引與本地提交檔案；不接手或結案舊 P2+ 輪。 |
| 文件 | canonical agent ID `/root/flow_docs_fix`；`gpt-6.1-sol`／`xhigh` | 唯一來源寫入者：`AGENTS.md`、`DATA_SOURCES.md`、`SOURCE_REGISTRY.md`、`R0_IMPLEMENTATION.md`、`ROADMAP.md`、`ROADMAP_EXECUTION.md`、本文件，共七檔；不改程式、不刷新索引或提交。 |
| 唯讀 reviewer | canonical agent ID `/root/flow_docs_review`；`gpt-6.1-sol`／`xhigh` | 只讀核對七檔差異、來源與產品邊界；不寫來源。 |
| 索引與 Git commit | canonical agent ID `/root/flow_docs_index`；`gpt-6-luna`／`medium` | 統籌接受及 freeze 後才更新涉及分區、驗 coverage，再只 stage／commit 核准七檔；不 push 或改來源。 |

runtime 只提供 subagent canonical ID，未提供 agent UUID；上述 ID 由本次統籌核對，不猜測或沿用舊 task ID。`PRODUCT_SPEC.md`、README 與 `STOCK_RESEARCH_PAGE.md` 僅核對穩定契約，不重寫。

目前狀態：**七檔文件修正已經統籌及唯讀 review 核對**；只接受文件流程與一致性，本段不宣稱產品能力完成。最終 freeze／索引／提交 receipt 留原 task，不為回寫 hash 再改文件。本次七檔總量上限 256 KiB、增補 diff 上限 24 KiB，額外暫存與測試產物配額為零；只做差異、連結與一致性檢查。統籌完成最終核對及 freeze 後依 [AGENTS](../AGENTS.md#git-結案) 做本次文件的輪末索引及本地 commit。角色不自行結案或啟動下一任務。

## 歷史與維護

舊角色 ID、交付狀態、測試及 commit 證據由 [Git／原 task](README.md#歷史查閱) 追溯；舊分派不覆蓋 AGENTS，也不恢復已刪除附件或舊統籌派工權。更新本文件時替換目前狀態，不追加逐輪日誌。
