# 協作與接手狀態

流程與角色配置由 [AGENTS](../AGENTS.md) 管理；能力與優先順序見 [ROADMAP](ROADMAP.md)，工作完成條件見 [執行清單](ROADMAP_EXECUTION.md)。

## 目前：M1 多日法人窗口新產品輪

2026-10-04，本輪由已驗收 master `7b3212a990361dcd3effb8e69b75ba8087b1c655` 建立新 branch／Orca worktree，已新建統籌與三個子角色。四角色 runtime、Git 與接手已由統籌複核；舊維護統籌已完成可見終端 `/subagents` 核對，啟動 gate 通過。新統籌已完整接手自主續作，舊維護統籌已結案，不再派本輪任務。W1 真資料／計算依賴及 W2 同截止 API／UI 核心操作均已有限接受；完整 M1 未完成。

共同 cwd／worktree：`C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/roadmap-m1-institutional-window-core-20261004`；branch：`roadmap-m1-institutional-window-core-20261004`；repo：`C:/Users/YiCheng/Desktop/taiwan-stock-research`；common Git dir：`C:/Users/YiCheng/Desktop/taiwan-stock-research/.git`。實際 runtime cwd 與 Git 根目錄一致，起始 HEAD／master 均為上述 SHA，初始 Git 乾淨。

Orca 登錄、branch、HEAD 與 runtime／Git 一致。可見 terminal handle 為 `term_03bd2ec7-251d-4ea1-845e-1f76ac47a01b`，已核 connected／writable／non-orphaned，終端實際顯示本輪工具操作與 GPT-6.1-Sol／ultra。第一 turn 完成且 Main 與三子角色 idle 時，舊維護統籌實際以 `/subagents` 核到 Main [default]、`/root/program`、`/root/documents`、`/root/index_git`，ID 與下表及 runtime／parent／配置相符；`No sub-agents running` 為 bootstrap idle，已 Esc 回 Main，未切角色。另核實 model／effort、cwd／branch／HEAD，首個 UTF-8 交接 task 已完整比對一致。

空白 MINGW shell `term_9e2a9f68-4938-4a52-82de-4449b95295d6` 已由舊維護統籌精確關閉，收據為 `ptyKilled=true`、無 agent；其他舊資源未碰，既有殘留及 NO-RETRY 不變。

| 角色 | 角色 thread ID／實際配置 | 寫入白名單與接手 |
| --- | --- | --- |
| 統籌 | `01a10611-ae2c-7f23-a1f8-f9eb0ce7d130`；`gpt-6.1-sol`／`ultra` | 已接手；本 checkpoint 只核證、派工與驗收，未寫來源。 |
| 程式 | `01a10613-ab4f-7350-8f69-34686ce02a97`；`gpt-6.1-sol`／`xhigh` | 已接手；W1 兩新檔、W2 下方11檔已有限接受，worker W1 只讀；交付停寫，沿用本 ID。 |
| 文件 | `01a10614-2017-7800-9ff6-20796eb42098`；`gpt-6.1-sol`／`xhigh` | 已接手；只准七份既有 docs：TASK_COORDINATION、SOURCE_REGISTRY、ROADMAP_EXECUTION、ROADMAP、DATA_SOURCES、STOCK_RESEARCH_PAGE、development-baseline/README；依 W2 實際驗收補最終契約／交接，交付停寫。 |
| 索引與 Git commit | `01a10614-7f52-7f30-8f64-dec6b9d5997a`；`gpt-6-luna`／`medium` | 已接手；零專案來源寫入。文件接受並 freeze 後才刷新涉及分區、驗 coverage、提交核准檔案；本地 merge 另待統籌核對提交後授權。 |

上表列角色 thread ID，不是四個獨立 top-level session。統籌 `parentThreadId=null`；三子角色的 `parentThreadId` 與 `source.subAgent.thread_spawn.parent_thread_id` 均為統籌 ID，depth 均為1，runtime 欄位 `sessionId` 也均為統籌 ID。實際模型／reasoning 由 `thread/read` 核實，不由設定或 prompt 推定。四角色初始未產品實作、來源研究、測試、索引、commit、merge 或清理。

App MCP 連線成功，八分區仍屬 master 原根。docs 分區為443 nodes／442 edges，已記錄的 partial／skipped／not-indexed files 均為0；README、ROADMAP、ROADMAP_EXECUTION、TASK_COORDINATION 四檔為 `metadata_changed`，已補讀本 worktree 原文。這不是本 worktree fresh 或完整 coverage 的證明；輪初不刷新或複製索引，待輪末更新。

本輪繼承零新增測試產物、附件、暫存與殘留及既有 NO-RETRY；舊資源不動。正式 Git 程式／測試來源不是 fixture 附件；原件、ZIP、測試 DB／tmp／cache／pycache／log附件新增仍0。文件限上述七份既有檔，合計至多增加24 KiB、TASK 本檔上限24 KiB，UTF-8 無 BOM／LF，不建立新 Markdown 或檢查附件。尚未 freeze／索引／commit／merge，封存起點仍為 `7b3212a`。

## 已結案獨立文件維護

前次獨立維護以 `1596fe1` 完成全部29份 Markdown 精簡；唯一 P2 修正只改 ROADMAP 一行並補 R0 §5.1 連結，已由 `7b3212a` 完成。舊維護統籌已確認 master 乾淨，無 push；該維護不是產品實作批次。舊維護 roster、索引落盤核定與最終收據留 Git／原 task，不沿用為本輪角色或新產物授權。

## 最近產品交付與原 roster

M3-P6e 特徵／籌碼獨立讀回隔離已有限接受，其16檔提交 `5ae84d2` 已在 master，包含主線文件維護 `453ca2b`；前輪 P6d 版本為 `0f8ac4a`。產品 session／terminal 的關閉與封存狀態沿用原 task，不從 Git 推定；歷史封存不代本輪啟動 gate。

P6e 原 worktree：`C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/roadmap-m3-stock-detail-independent-read-isolation-20261004`；branch 同目錄名；起始 HEAD：`0f8ac4ab3af8ec44353c2181eb18ae3c9a9fe6cb`。原可見 terminal：`term_935e0735-4482-4cda-88a7-c60a0fadcc68`。

| 原產品角色 | session ID | 已核實配置 |
| --- | --- | --- |
| 統籌 | `01a104ef-f17a-7f81-9ba6-c2d7483d6891` | `gpt-6.1-sol`／`ultra` |
| 程式 | `01a104f2-0748-74a1-bc7a-1bc97afe4433` | `gpt-6.1-sol`／`xhigh` |
| 文件 | `01a104f2-50d4-79e2-96a2-d4f9ccb864f8` | `gpt-6.1-sol`／`xhigh` |
| 索引與 Git commit | `01a104f2-91b0-7ec3-94b0-ccc982949b5a` | `gpt-6-luna`／`medium` |

原角色不作新輪 roster，已交接舊統籌不得重派，也不恢復舊角色。M2-P2 後的停止要求已由後續明確恢復授權解除；本輪為新建角色，runtime／Git／接手與可見終端 `/subagents` 啟動 gate 均已通過，由新統籌依下方真資料及必要 gate 核定實作派工。

P6e 已接受兩表讀回隔離、必要 API／App、六個具名桌面操作與同 fixture 六表不變；原生／DOM.click 範圍見[個股頁 §17](STOCK_RESEARCH_PAGE.md#17-m3-p6e個股特徵籌碼獨立區塊讀回隔離)。未增加多日法人、新 Plan 或完整 M1／M3。P6c 有效歷史窄版溢出未通過，physical canvas、真正截止表單提交及其他未覆蓋 typed／legacy 讀回仍待驗。正式 DB、官方／availability／PIT、正向原件及必要磁碟 gate 保留。

## 下一核心目標與跨輪停滯

| 接手項目 | 狀態與動作 |
| --- | --- |
| 本輪單一核心目標 | M1：同研究截止查看5／20交易日外資、投信、自營商各別淨買賣超及來源／缺日。W1 具名依賴與 W2 同截止操作已有限接受，範圍限 TPEx 3105／6488、2026-10-02。 |
| 已有真實證據與缺口 | 20日真原件、完整22開市日與12窗口重算見[來源 §13](SOURCE_REGISTRY.md#13-m1-w1tpex-多日法人與完整有界交易日)；新 first POST／零外網 GET 與具名操作見[個股頁 §18](STOCK_RESEARCH_PAGE.md#18-m1-w2同截止法人窗口與原件追溯)。其他日期／標的／TWSE、修訂／PIT、研究條件／保存仍缺，P2b 不變。 |
| 下一步與實作前條件 | 結案 gate 後由新統籌先驗同 CSV 115/09/01、02真原件及兩股22日金融欄位，核新 policy／窗口，才接9/30、10/01與既有10/02三截止切換。既有日曆不代新日原件；精確工作 ID／白名單另縮限，本輪不加實作，不重做 P4a。 |
| 核心拆工與完成條件 | 依實際取得及驗證，分批核定窗口／交易日／缺日處理與版本，逐欄重算5／20日及邊界，再驗同截止 API／UI 具名操作。多日與完整交易日依賴→計算→API／UI 是本輪核心，不預設可靠性批次；孤立 observed-session、fixture、planning 或 unknown 標示不算依賴解除。 |
| 改選條件 | M1 沒有新取得路徑時，任何實作前依新證據改選必要 gate 齊備的最小 M3 計畫操作，列來源／availability、decision／execution、版本、tick／費稅／合法時段及必要磁碟保存／跨程序讀回條件。仍無可執行項則等待，不開空轉、隔離或重複審查輪。 |
| 繼承停滯的兩個已驗收批次 | 起始統籌已核當時最近兩批 Git 變更與文件：P6d `0f8ac4a`、P6e `5ae84d2` 均為讀回可靠性改善；未接多日法人或新 Plan，未解除當時已列核心來源／時間依賴。 |
| 連續未推進核心批次 | 現為0：繼承至少2批（更早未知）由 W1 真依賴驗收重置，W2 核心操作驗收後仍0；P6d／P6e 仍為可靠性。已審最近兩批重新選 M1 來源→計算→產品；每批分報操作、依賴、可靠性與剩餘，只有前兩項真證據才重置。 |
| 啟動與文件維護 | 舊獨立維護及本輪啟動／roster 更新均不是產品實作批次，不增加或重置上述計數。 |

M1 來源、計算、產品驗收與 M3 必要 gate 見[執行清單 §2.1](ROADMAP_EXECUTION.md#21-近期里程碑接線映射)。本輪仍為單一 M1；下一核心已由統籌核定，改選證據與理由留原 task。

### M1-W1：有限依賴已接受

統籌以實際 production consumer 驗22 GET／22 captures、完整22開市日、兩股40列／880金融原字串及12窗口 net 的獨立原件與 buy－sell 重算；guard 磁碟／mutation／未准入網路0、exit 0、零新增檔案。來源、policy／版本、整數／缺日及有限參考詳述已移至[來源契約 §13](SOURCE_REGISTRY.md#13-m1-w1tpex-多日法人與完整有界交易日)；命令、UTC、full hashes、probe 原失敗與版本收據留原 task。

本批分報：**核心操作0；已解除依賴為兩股／單 cutoff 多日原件、完整有界日曆與計算；可靠性0。** 本批當時尚缺 API／UI及範圍外／修訂／PIT／研究條件。實際依賴驗收重置停滯0，不倒改 P6d／P6e 或以文件更新重置。

### M1-W2：同截止核心操作已有限接受

原程式角色沿用，worker W1 只讀；最終11檔白名單如下：

| 範圍 | 精確檔案 |
| --- | --- |
| backend app | 新 `backend/app/institutional_windows.py`、`backend/app/stock_overview.py`、`backend/app/api.py` |
| backend test | `backend/tests/test_institutional_windows.py`、`backend/tests/test_institutional_daily.py`（僅禁用 window env／兩處舊斷言同步，保留 P2b） |
| frontend | `frontend/src/types.ts`、`frontend/src/api.ts`、`frontend/src/App.tsx`、`frontend/src/components/StockOverview.tsx`、`frontend/src/components/StockOverview.test.tsx` |
| preview | 新 `tools/institutional-window-preview.cjs` |

統籌已驗實際 native first POST 新取22 GET／2,903,562 bytes，22 body hash 與 W1 相符但新 capture／receipt 分開；兩股40原列、360 API字串／12 net 重算、共用截止／版本及19表全欄／typeof 不變、guard0、reader exit0。具名操作／原生與 DOM 邊界集中[§18](STOCK_RESEARCH_PAGE.md#18-m1-w2同截止法人窗口與原件追溯)，非保存重播。

本批分報：**核心操作增量為兩股單截止查看5／20日三類 net／來源／缺日；已解除接線依賴為同截止 API／UI（不重計 W1 來源／日曆）；可靠性0；停滯仍0。** 其他日期／標的／TWSE、PIT／修訂、研究條件／保存及完整 M1 仍缺。必要 API／SSR／noEmit／mock HTTP 有限接受；舊 ZIP fixture 未重跑，build／canvas／導航 race 未驗。

本次 owned API／Node／esbuild 與8781／8782 listeners、Orca tab 已核關閉；serve 主動中斷 exit1，shutdown db_preserved=true／guard0，驗收與清理分報。新增測試附件／tmp／raw／DB 殘留0；舊 NO-RETRY 尾段不變。

正式索引已核定、未執行：本輪前綴 `taiwan-stock-research-roadmap-m1-institutional-window-core-20261004-` 的 backend-app／backend-worker／backend-tests／frontend-src／tools／docs 共6區，DB固定 `C:/Users/YiCheng/cbm-cache/<ID>.db`，各≤24 MiB、合計≤64 MiB；逐區正常路徑 response／log各1、stage DB1≤24 MiB、sidecars aux≤16 MiB；最終 coverage 回傳自有 logs≤6檔／48 KiB，根為 cache/logs。這是本輪核定配額，非工具硬限或舊維護額度。App頂層呼叫每區一次；任一 error／超額停餘項、NO-RETRY，不改 cache／ACL／daemon，CBM0.10.8內部恢復不可設0。只核清 exact 回傳且自有／非 reparse／未占用路徑；失敗缺 exact path 就列未核清缺口，不掃 cache。6正式可重建 DB 保留至外部 owner 接手，移除 worktree 後按6 ID delete_project／核，不作下一輪 fresh；舊8索引不動。

下一步：文件接受／freeze→本輪索引／coverage→統籌批准 commit／核→授權本地 merge→新可見統籌及外部清理接手；均 pending，無 push。精確執行／封存收據留原 task，不為 hash反覆回寫。文件交付停寫，沿用本 ID。

## 未解驗證與資源限制

下表沿用整理前最後已知收據；本次未重新盤點或清理，不作即時刪除 gate。已刪除項不重做；審核拒絕項不得重試、換工具、掃共享目錄或刪父目錄。精確歷史收據由 Git `5ae84d2:docs/TASK_COORDINATION.md` 與對應原 task 查閱。

| 項目 | 最後已知結果／後續限制 |
| --- | --- |
| R0-B2 verifier | 完整 snapshot／body／receipt／registry pins tuple 未齊，真實檔案／snapshot 整合待驗，70個既有案例未跑；不重複搜尋或建 fixture 冒稱來源接入。 |
| P6d 五 DB 刪前流程 | 五 DB／十五 aux 與兩 logs 刪後缺席已驗；刪前只核 leaf／exclusive open，未核 all ancestors 與十五 aux。不得追認完整刪前 gate；不補刪除或重試。 |
| P6c blocked logs | 兩個 logs 共717 bytes（295／422 bytes）；immediate gate／刪除均在 CreateProcess 前被拒，未執行，NO-RETRY。兩完整路徑見下方。 |
| P4 blocked logs | 兩個 logs 共713 bytes（293／420 bytes）；刪除被拒，未執行，NO-RETRY。兩完整路徑見下方。 |
| P2 HAR | `C:/Users/YiCheng/.agent-browser/tmp/har/har-1791044803009.har`，64,885 bytes；清理遭審核拒絕，未執行，NO-RETRY。 |
| P1 index logs | 3個共1,139 bytes；295 bytes 項刪除被拒，另兩個各422 bytes未嘗試。精確路徑留原 storage task；未清，不得推定全清。 |
| M1 成交量舊 worktree | `C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/roadmap-m1-volume-exact-presentation-20261003`，最後3,528,690 bytes；worktree／branch移除被拒，NO-RETRY。索引／logs已清不代表該根已清。 |
| legacy volume 整合空根 | `C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/roadmap-r1-a2-legacy-volume-integration-20261003`，最後0 bytes；空目錄被占用，刪除失敗，不重試。PTY終止未核。 |
| selected-invalid 空根／logs | `C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/roadmap-r1-a2-selected-invalid-20261003`，最後0 bytes；空根被占用，刪除失敗。兩logs共628 bytes被拒，未刪；更早兩logs共545 bytes亦被拒。路徑留原task，NO-RETRY。 |
| M1-P2a 測試根 | `C:/Users/YiCheng/AppData/Local/Temp/taiwan-stock-m1p2a-01a0fe7e`，243 entries／11 files／993,443 bytes，已超原entries上限；code-tests／live清理被拒，未執行。conftest另建的default Temp _TEST_ROOT名稱／大小未知，不掃Temp猜測。 |
| 更早 M1 測試根 | `C:/Users/YiCheng/AppData/Local/Temp/taiwan-stock-m1-01a0fe5a`，118 entries／105 files／17,319,956 bytes；UI／code-tests清理被拒，未執行。 |
| 後續落盤 | 繼承原零新增測試／附件／暫存／殘留限制。必要磁碟驗收保持待驗；不得換session、根目錄或改名重置上限。 |

四個已知 blocked log 的完整路徑：

- `C:/Users/YiCheng/cbm-cache/logs/taiwan-stock-research-roadmap-m3-stock-detail-quote-read-isolation-20261004-backend-tests-1791076431.log`
- `C:/Users/YiCheng/cbm-cache/logs/taiwan-stock-research-roadmap-m3-stock-detail-quote-read-isolation-20261004-tools-1791076500.log`
- `C:/Users/YiCheng/cbm-cache/logs/taiwan-stock-research-roadmap-m3-portfolio-value-read-validation-20261004-backend-tests-1791054858.log`
- `C:/Users/YiCheng/cbm-cache/logs/taiwan-stock-research-roadmap-m3-portfolio-value-read-validation-20261004-tools-1791054866.log`

## 歷史與維護

只更新現況、下一核心交接與未解限制，不追加逐輪流水。歷史 roster／實際模型、首跑失敗／補驗、freeze／索引／commit／merge 及清理收據留 Git／原 task；舊分派不恢復派工權。查閱方式見[文件索引](README.md#歷史查閱)。
