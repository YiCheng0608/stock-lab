# 協作與接手狀態

本文件只留目前角色、接手與下一步；流程依 [AGENTS](../AGENTS.md)，能力與優先順序查 [ROADMAP](ROADMAP.md)。

## 本輪：M1-P1 截止一致與來源可追溯總覽

使用者最新明示「這一個索引任務結束後，幫我commit，commit完請開始執行roadmap的階段任務了。」獨立文件維護與剩餘 `backend/tests/test_stock_day_capture.py` 已分別版本封存；新統籌依此接手 [M1](ROADMAP.md#接下來的順序近期產品里程碑)。來源統籌 session `01a0fde3-6be4-77a2-b86e-e033f8d7fd3a` 已停止派工，舊禁止 commit／派下一輪文字不再作本輪限制；本地 commit 不含 push 或歷史重寫。

共同 repo：`C:\Users\YiCheng\Desktop\taiwan-stock-research`；接手時乾淨 HEAD：`d8229101e514e7b899e6f4b3b672530f4d00a960`。本輪統籌 session `01a0fe5a-b44a-7be0-b24e-e7907f7f3916` 已由環境 `CODEX_SESSION_ID`／`THREAD_ID` 核實；runtime 未提供可核實的統籌 model／reasoning，不猜測。三個有效 subagent 皆在同一 session 明確指定建立參數並確認接手，未沿用舊 task。

### 本輪 roster 與寫入範圍

| 角色 | 本輪 ID／實際建立參數 | 寫入／驗收範圍 |
| --- | --- | --- |
| 統籌 | session `01a0fe5a-b44a-7be0-b24e-e7907f7f3916`；runtime 未提供可核實的 model／reasoning | 核定 M1 操作、資料範圍、窗口與版本、驗收及提交檔案；接受文件後才 freeze。 |
| 程式 | canonical agent ID `/root/m1_code_configured`；`gpt-6.1-sol`／`ultra` | `backend/app/api.py`、`backend/app/stock_overview.py`、`backend/tests/test_stock_overview.py`、`frontend/src/App.tsx`、`frontend/src/api.ts`、`frontend/src/types.ts`、`frontend/src/styles.css`、`frontend/src/components/StockOverview.tsx`、`frontend/src/components/StockOverview.test.tsx`；不改 docs 或自行修改規格。 |
| 文件 | canonical agent ID `/root/m1_docs`；`gpt-6.1-sol`／`xhigh` | `docs/STOCK_RESEARCH_PAGE.md`、`ROADMAP.md`、`ROADMAP_EXECUTION.md`、本文件；不改程式、AGENTS、索引或 Git。 |
| 索引與 Git commit | canonical agent ID `/root/m1_index`；`gpt-6-luna`／`medium` | freeze 後才刷新涉及分區、驗 coverage，並只 stage／commit 統籌核准檔案；不改來源或 push。 |

runtime 僅提供 subagent canonical ID，未提供 agent UUID。最初未指定配置的 `/root/m1_code` 在派工前已被 interrupt，不是有效工作角色。所有角色不得自行結案或啟動下一任務；共同 repo 與互不衝突的白名單已由統籌核對。

### 接手成果、缺口與下一步

1. **完成及驗收邊界**：獨立文件維護已接受文件流程與一致性，不增加產品完成度。R1-A2-P1-identity 與 P2+ 成交額政策、程式補強保留原有限 review；缺額／明確零的單一離線 fixture capture→SQLite→API 已有限驗收並版本封存，不升格官方真實樣本、全市場或 R1-A2 整體完成。詳細契約見 [DATA_SOURCES](DATA_SOURCES.md#r1-a2-p2-成交金額可得狀態有限接受)。
2. **本批有限接受與尚缺項**：M1-P1 的 TWSE 1101／2330、2026-10-01 單日 selected 真實價格六欄、detail／總覽 API 一致、指定截止排除與晚於價格提示、桌面／窄版具名操作及後端邊界回歸、前端 SSR／型別／production build 已有限 review；保留大型 JS chunk 警告，精確契約及支持範圍見[個股頁 §9](STOCK_RESEARCH_PAGE.md#9-m1-p1截止一致與來源可追溯總覽)。完整 M1 的法人 5／20 日、交易日、事件與研究條件未完成。R1-A2 的 legacy migration、其他 invalid／拒收磁碟整合、正式 DB、逐市場／session／欄位 coverage、availability／歷史／PIT 與量截整／TAIEX 合成欄位風險不變。其餘 R0 與 B2 snapshot／body／receipt／attempt／ordinal／pins 缺口維持原邊界，不重複搜尋或建 specimen。
3. **下一步與依賴／完成條件**：本輪文件核對與版本封存後，依 [M1 接線映射](ROADMAP_EXECUTION.md#21-近期里程碑接線映射) 核定法人／交易日來源及用途准入、逐法人單位／缺日與可驗 5／20 日窗口。未准入 legacy 不當已完成，不由 P1 宣稱 M2 就緒；各區塊保留原日期／時間、版本與 unknown／unavailable 原因，來源／數值與產品操作由統籌驗收。
4. **freeze／索引／commit**：程式與具名驗收已接受；文件核對後由統籌 freeze，索引角色刷新、驗 coverage 並提交核准檔案。最終 receipt 留本輪 task，不為回寫 hash 反覆改文件。

本輪文件只修改上述四個既有檔案，總增補上限 **32 KiB**，額外附件／暫存配額為零；只做差異、連結與一致性檢查。程式、真實 capture／UI／build 使用統籌核定的唯一根 `C:\Users\YiCheng\AppData\Local\Temp\taiwan-stock-m1-01a0fe5a`，統一上限 **300 entries／50 MiB**，各建立者清自身、統籌最終清理，測試與清理結果分報；本批不 collect、不操作正式 DB。未清理或失敗不得冒稱已刪除，最終結果留本輪 task。

UI 與 code-tests 清理被自動審核拒絕，沒有執行；殘留路徑／大小與最終清理收據留本輪 task。有效驗收不因清理失敗被否定；後續保持隔離與統一配額，不為繞過拒絕再刪整個 root。

## 歷史與維護

舊角色 ID、交付狀態、測試及 commit 證據由 [Git／原 task](README.md#歷史查閱) 追溯；舊分派不覆蓋 AGENTS，也不恢復已刪除附件或舊統籌派工權。更新本文件時替換目前狀態，不追加逐輪日誌。
