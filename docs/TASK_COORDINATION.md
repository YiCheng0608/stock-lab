# 協作與接手狀態

流程與角色配置由 [AGENTS](../AGENTS.md) 管理；能力與優先順序見 [ROADMAP](ROADMAP.md)，工作完成條件見 [執行清單](ROADMAP_EXECUTION.md)。

## 目前：M1-W3 法人窗口截止擴充新產品輪

2026-10-04，本輪由已驗收 master `f716526ddcd98ddbaa155c2fd9fe70f776ed4e2a` 建立新 branch／Orca worktree，已新建統籌及三個子角色。統籌已複核四角色 runtime、Git、loaded 狀態與接手，舊統籌已完成可見 `/subagents` 同組 ID核對，完整啟動 gate通過。**M1-W3新增兩日真來源、三截止計算及 actual API／native具名操作已有限接受；完整 M1未完成。** 下方七份文件更新後待統籌驗收／freeze，本輪 index／commit／master merge尚未執行。下一單一核心選定 M1-W4，尚未取得新來源或實作。

共同 cwd／worktree：`C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/roadmap-m1-window-cutoff-expansion-20261004`；branch：`roadmap-m1-window-cutoff-expansion-20261004`；repo：`C:/Users/YiCheng/Desktop/taiwan-stock-research`；common Git dir：`C:/Users/YiCheng/Desktop/taiwan-stock-research/.git`。四角色實際 runtime cwd 與 Git 根目錄一致，起始 HEAD／master 均為上述 SHA，改文書前 Git 乾淨。

Orca 登錄、branch、HEAD 與 runtime／Git 一致。唯一本輪可見 terminal handle 為 `term_3ed777be-064c-4a05-8492-0b3ae2134ddd`，已實核 connected／writable／non-orphaned，終端顯示本輪工具操作與 GPT-6.1-Sol／ultra，對應本輪統籌。舊統籌在四角色 runtime idle 時實際操作 `/subagents`，`source=screen` 顯示 Main [current/default] 及三個 `/root/` child，四 ID 均與下表及 runtime 相同；`No sub-agents running` 只表示 bootstrap idle，已 Esc 回 Main，未選 child。另核配置／parent／session／depth／cwd 與三次 `fork_turns=none` 收據一致，首個 UTF-8 任務全文比對一致。首次 timeout exit1／未送 task及後續啟動完整收據留原 task，不重建或 resume 另一 thread，不補造或重試。

本輪原空白 shell `term_efdd5217-b8d9-4dce-a725-762b68888ec9` 已 exact close；`ptyKilled=false`，後驗 orphaned、connected／writable=false、exitCause=`operator_close`，不重試或宣稱 PTY 已 kill。其他舊資源未碰，既有殘留及 NO-RETRY 不變。

| 角色 | 角色 thread ID／實際配置 | 寫入白名單與接手 |
| --- | --- | --- |
| 統籌 | `01a10690-dce1-7e81-901c-4051c657d2e5`；`gpt-6.1-sol`／`ultra` | 已正式接手；已接受 W3有限來源／產品驗收，待文件驗收後 freeze；W4須新來源 gate才派精確實作。 |
| 程式 | `01a10695-0577-7450-ac80-85d1d6263cc5`；`gpt-6.1-sol`／`xhigh` | W3下方8檔交付已接受，停寫沿用本 ID；不取得／實作 W4或擴白名單。 |
| 文件 | `01a10695-9514-7aa3-b1ef-aa960a0e3d7d`；`gpt-6.1-sol`／`xhigh` | DOC-FINAL1只准既有 TASK_COORDINATION、SOURCE_REGISTRY、ROADMAP_EXECUTION、ROADMAP、DATA_SOURCES、STOCK_RESEARCH_PAGE、development-baseline/README七檔；交付停寫待驗收。 |
| 索引與 Git commit | `01a10696-22b1-7502-aa33-8da59d536742`；`gpt-6-luna`／`medium` | 已接手；零專案來源寫入。接受文件並 freeze 後才刷新相關分區及驗 coverage；核准 commit 才提交，統籌核提交後另准本地 merge，目前均未執行。 |

上表列角色 thread ID，不是四個獨立 top-level session。統籌 `parentThreadId=null`，四角色 `forkedFromId=null`；三子角色由本輪統籌以 `fork_turns=none` 新建，其 `parentThreadId` 與 `source.subAgent.thread_spawn.parent_thread_id` 均為統籌 ID，depth 均為1，agent_path 依序為 `/root/program`、`/root/documents`、`/root/index_git`。四者 runtime `sessionId` 均為統籌 ID。統籌重新 `thread/read` 核實模型／reasoning／cwd／parent，loaded list 核四者均 loaded，各角色自行核 Git 與接手後回報；不由設定或 prompt 推定。同輪沿用這組 ID，不恢復舊角色。

App MCP連線成功，前輪6項已精確清理，現僅 master原根8區；本輪新根未索引。master docs受影響七檔 recording_status=`complete`、`no_recorded_issue`，freshness均為 `metadata_changed`，已採本 worktree原文。AGENTS在既有分區根外亦用原文；原根 coverage不證本輪 fresh或完整，不中途刷新或複製索引，文件接受／freeze後才由索引角色更新。

本輪繼承零新增測試附件／暫存／殘留及既有 NO-RETRY；測試用途的原件／ZIP／DB／tmp／cache／pycache／log／artifact附件新增仍0，來源原件僅 process memory、raw落盤0。正式程式／測試來源8檔已交付；DOC-FINAL1正式文書限七個既有檔，淨增加合計≤24 KiB、本 TASK≤24 KiB，UTF-8無 BOM／LF，不建 Markdown附件／manifest。Bootstrap與文件更新不算產品實作批次；W3真驗收已接受，freeze=false，本輪 index／commit／merge未執行，版本起點為 `f716526`；後續正式索引落盤須由統籌在原 task另核，不把附件0稱為全 cache0。

## 已結案獨立文件維護

前次獨立維護以 `1596fe1` 完成全部29份 Markdown 精簡；唯一 P2 修正只改 ROADMAP 一行並補 R0 §5.1 連結，已由 `7b3212a` 完成。舊維護統籌已確認 master 乾淨，無 push；該維護不是產品實作批次。舊維護 roster、索引落盤核定與最終收據留 Git／原 task，不沿用為本輪角色或新產物授權。

## 前輪版本接手與歷史產品 roster

前輪 M1-W1／W2 的19檔已接受 freeze／index／commit／master merge，版本為 `f716526ddcd98ddbaa155c2fd9fe70f776ed4e2a`，以原 task 最終 receipt 為準；原文的 pending 交接狀態已過時，不擴張功能驗收。前輪 worktree／branch 為 `roadmap-m1-institutional-window-core-20261004`，原統籌 `01a10611-ae2c-7f23-a1f8-f9eb0ce7d130` 與三角色 `01a10613-ab4f-7350-8f69-34686ce02a97`、`01a10614-2017-7800-9ff6-20796eb42098`、`01a10614-7f52-7f30-8f64-dec6b9d5997a` 只作前輪接手與清理辨識，不是當前 roster。

CLEAN-OLD-W2已完成並由新統籌獨立後驗：實核舊輪 idle／clean／merged及 owned範圍後，索引角色精確關閉舊 terminal，`ptyKilled=true`且後驗無連線／不可寫／orphaned；**本輪新統籌**一次封存前輪 root含三 child，四 thread均在 archived_sessions／notLoaded，歷史保留。索引角色續以 Orca移除 exact舊 worktree／branch、逐個 delete前輪6項；舊根／branch及6 exact DB／固定 -wal／-shm／-journal均已核缺席，本輪 root／branch／HEAD不變，App僅 master8。範圍內剩0，沒有擴掃或重試；其他 cache aux／logs未核清，既有 NO-RETRY不變，不從此推定全清。

M3-P6e 特徵／籌碼獨立讀回隔離已有限接受，其16檔提交 `5ae84d2` 已在 master，包含主線文件維護 `453ca2b`；前輪 P6d 版本為 `0f8ac4a`。產品 session／terminal 的關閉與封存狀態沿用原 task，不從 Git 推定；歷史封存不代本輪啟動 gate。

P6e 原 worktree：`C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/roadmap-m3-stock-detail-independent-read-isolation-20261004`；branch 同目錄名；起始 HEAD：`0f8ac4ab3af8ec44353c2181eb18ae3c9a9fe6cb`。原可見 terminal：`term_935e0735-4482-4cda-88a7-c60a0fadcc68`。

| 原產品角色 | session ID | 已核實配置 |
| --- | --- | --- |
| 統籌 | `01a104ef-f17a-7f81-9ba6-c2d7483d6891` | `gpt-6.1-sol`／`ultra` |
| 程式 | `01a104f2-0748-74a1-bc7a-1bc97afe4433` | `gpt-6.1-sol`／`xhigh` |
| 文件 | `01a104f2-50d4-79e2-96a2-d4f9ccb864f8` | `gpt-6.1-sol`／`xhigh` |
| 索引與 Git commit | `01a104f2-91b0-7ec3-94b0-ccc982949b5a` | `gpt-6-luna`／`medium` |

原角色不作新輪 roster，已交接舊統籌不得重派，也不恢復舊角色。M2-P2後停止要求已由後續明確恢復授權解除；本輪 runtime／Git／接手及可見 `/subagents`已核，同輪沿用新三 child。W3具名產品已驗，下一 W4實作仍等新來源 gate。

P6e 已接受兩表讀回隔離、必要 API／App、六個具名桌面操作與同 fixture 六表不變；原生／DOM.click 範圍見[個股頁 §17](STOCK_RESEARCH_PAGE.md#17-m3-p6e個股特徵籌碼獨立區塊讀回隔離)。未增加多日法人、新 Plan 或完整 M1／M3。P6c 有效歷史窄版溢出未通過，physical canvas、真正截止表單提交及其他未覆蓋 typed／legacy 讀回仍待驗。正式 DB、官方／availability／PIT、正向原件及必要磁碟 gate 保留。

## 下一核心目標與跨輪停滯

| 接手項目 | 狀態與動作 |
| --- | --- |
| 本輪單一核心目標 | M1-W3已有限接受：TPEx3105／6488新增9/30、10/1並保留10/2，native切三 cutoff各看5／20日三類 net／來源／缺日0。研究條件／PIT／保存不在本子能力；完整 M1未完成。 |
| 已有真實證據與缺口 | 新9/1、9/2與22日全金融、完整有界日曆及36 net重算見[來源 §14](SOURCE_REGISTRY.md#14-m1-w3三截止法人來源與窗口)；actual API首次新觀測／同 held24原件及 native三 cutoff見[個股頁 §19](STOCK_RESEARCH_PAGE.md#19-m1-w3三截止法人窗口與原件追溯)。其他日期／標的／TWSE、修訂／PIT、研究條件／保存仍缺，P2b不變。 |
| 下一單一核心及實作前條件 | M1-W4同兩股新增2026-09-29、保留三 cutoff，使用者切四截止各看5／20日 net／來源／缺日。候選 dataset11856 CSV `d=115/08/31`＋dataset11391月 index `date=2026/08/01`皆尚未真取；先核新增兩股全金融／單位／全列日期結構，8月 index於新8/31～10/2有限範圍的正面集合／閉日，及新 calendar／policy／外部 pins／請求上限／觀測版本與缺日契約，不能沿 W3白名單放行。現在只選題交接，不在本輪取得或實作 W4。 |
| 核心拆工與完成條件 | W4先實際解除上述來源／完整23 sessions依賴；9/29應恰20 sessions，5日起9/21、20日起8/31。真來源 gate通過才精確派工／核新版本、獨立重算四 cutoff48 net及邊界，再驗 native四截止／來源／缺日。每窗只採≤cutoff，缺／錯日不補零、縮窗或較早／未來 fallback，保持非 PIT；孤立 fixture／planning／unknown標示不算依賴解除，每批分報操作、依賴、可靠性及剩餘。 |
| 改選條件 | M1 沒有新取得路徑時，任何實作前依新證據改選必要 gate 齊備的最小 M3 計畫操作，列來源／availability、decision／execution、版本、tick／費稅／合法時段及必要磁碟保存／跨程序讀回條件。仍無可執行項則等待，不開空轉、隔離或重複審查輪。 |
| 繼承停滯的兩個已驗收批次 | 起始統籌已核當時最近兩批 Git 變更與文件：P6d `0f8ac4a`、P6e `5ae84d2` 均為讀回可靠性改善；未接多日法人或新 Plan，未解除當時已列核心來源／時間依賴。 |
| 連續未推進核心批次 | 現為0：繼承至少2批（更早未知）由 W1真依賴重置，W2真操作後仍0，W3新增日期／三截止真驗收後維持0；P6d／P6e仍為可靠性歷史。已審拆工重新選 M1來源→計算→產品；只有核心操作／真依賴解除才重置，不因換輪歸零。 |
| 啟動與文件維護 | 舊獨立維護、本輪 bootstrap／roster及 DOC-FINAL1均不是產品實作批次，不增加或重置計數。 |

M1來源、計算、產品驗收與 M3必要 gate見[執行清單 §2.1](ROADMAP_EXECUTION.md#21-近期里程碑接線映射)。本輪核心為 W3，下一 W4已由統籌選定，仍待真來源／新版本；改選證據與理由留原 task。

### M1-W1：有限依賴已接受

統籌以實際 production consumer 驗22 GET／22 captures、完整22開市日、兩股40列／880金融原字串及12窗口 net 的獨立原件與 buy－sell 重算；guard 磁碟／mutation／未准入網路0、exit 0、零新增檔案。來源、policy／版本、整數／缺日及有限參考詳述已移至[來源契約 §13](SOURCE_REGISTRY.md#13-m1-w1tpex-多日法人與完整有界交易日)；命令、UTC、full hashes、probe 原失敗與版本收據留原 task。

本批分報：**核心操作0；已解除依賴為兩股／單 cutoff 多日原件、完整有界日曆與計算；可靠性0。** 本批當時尚缺 API／UI及範圍外／修訂／PIT／研究條件。實際依賴驗收重置停滯0，不倒改 P6d／P6e 或以文件更新重置。

### M1-W2：同截止核心操作已有限接受

前輪程式角色同輪沿用，worker W1 只讀；當時最終11檔白名單如下，不作 M1-W3 寫入授權：

| 範圍 | 精確檔案 |
| --- | --- |
| backend app | 新 `backend/app/institutional_windows.py`、`backend/app/stock_overview.py`、`backend/app/api.py` |
| backend test | `backend/tests/test_institutional_windows.py`、`backend/tests/test_institutional_daily.py`（僅禁用 window env／兩處舊斷言同步，保留 P2b） |
| frontend | `frontend/src/types.ts`、`frontend/src/api.ts`、`frontend/src/App.tsx`、`frontend/src/components/StockOverview.tsx`、`frontend/src/components/StockOverview.test.tsx` |
| preview | 新 `tools/institutional-window-preview.cjs` |

統籌已驗實際 native first POST 新取22 GET／2,903,562 bytes，22 body hash 與 W1 相符但新 capture／receipt 分開；兩股40原列、360 API字串／12 net 重算、共用截止／版本及19表全欄／typeof 不變、guard0、reader exit0。具名操作／原生與 DOM 邊界集中[§18](STOCK_RESEARCH_PAGE.md#18-m1-w2同截止法人窗口與原件追溯)，非保存重播。

本批分報：**核心操作增量為兩股單截止查看5／20日三類 net／來源／缺日；已解除接線依賴為同截止 API／UI（不重計 W1 來源／日曆）；可靠性0；停滯仍0。** 其他日期／標的／TWSE、PIT／修訂、研究條件／保存及完整 M1 仍缺。必要 API／SSR／noEmit／mock HTTP 有限接受；舊 ZIP fixture 未重跑，build／canvas／導航 race 未驗。

W2 owned API／Node／esbuild 與8781／8782 listeners、Orca tab 已核關閉；serve 主動中斷 exit1，shutdown db_preserved=true／guard0，驗收與清理分報。當時新增測試附件／tmp／raw／DB 殘留0；舊 NO-RETRY 尾段不變。

前輪正式6區索引／coverage曾完成，前綴 `taiwan-stock-research-roadmap-m1-institutional-window-core-20261004-`，後綴為 backend-app／backend-worker／backend-tests／frontend-src／tools／docs；6 DB合計44,302,336 bytes、每區≤24 MiB／合計≤64 MiB。根移除後已按6 ID delete_project，exact DB及固定 -wal／-shm／-journal皆核缺席，不作新輪 fresh。兩個 returned logs（287／414 bytes）早先已驗缺席，但刪前 `Split-Path AmbiguousParameterSet` 未 fail-fast，不能後驗追認刪前 gate；其他 cache aux狀態未知。前輪索引 error／超額停餘項的 NO-RETRY 限制保留，CBM0.10.8內部恢復不可設0。完整路徑／命令與逐區收據留原 task；只核清 exact 自有／非 reparse／未占用路徑，缺 exact path 列缺口，不掃 cache，不改 cache／ACL／daemon，不動 master8。

前輪版本封存／master merge及核定外部清理已完成；本輪可見啟動 gate通過，W3有限驗收已接受，freeze／index／commit／merge未執行，無 push。精確封存／清理收據留原 task，不為 hash反覆回寫；本輪文件交付即停寫待統籌接受。

### M1-W3：三截止核心操作已有限接受

程式角色本輪8檔已交付接受，白名單如下；W4尚無實作授權：

| 範圍 | 精確檔案 |
| --- | --- |
| backend app／worker | `backend/app/institutional_windows.py`、`backend/app/stock_overview.py`、`backend/worker/tpex_institutional_window.py` |
| backend test | `backend/tests/test_institutional_windows.py` |
| frontend／preview | `frontend/src/types.ts`、`frontend/src/components/StockOverview.tsx`、`frontend/src/components/StockOverview.test.tsx`、`tools/institutional-window-preview.cjs` |

統籌已接受新兩日 probe與 first actual API POST兩個獨立真觀測、44 selected原列全金融／完整日曆／36 net及重複 API字串核對；native兩股依序切三 cutoff、來源原列、390×844新9/1原列、9/29與 TWSE拒用／恢復均具名有限接受。首次取得是 actual API，native讀同 held instance；完整來源及數值集中[§14](SOURCE_REGISTRY.md#14-m1-w3三截止法人來源與窗口)，操作與 setup／trusted事件界線集中[§19](STOCK_RESEARCH_PAGE.md#19-m1-w3三截止法人窗口與原件追溯)。

本批分報：**核心操作增量＝兩股新增9/30／10/1並可 native切三截止查看5／20日 net／來源／缺日0，保留10/2；已解除真依賴＝新兩日期原件及三截止窗口／API／UI；可靠性0；停滯維持0。** 完整 M1、範圍外標的／日期／TWSE、PIT／修訂、研究條件／保存仍缺。

worker7／actual router5／SSR24／full-src noEmit／mock product HTTP36 net與 BigInt已有限接受。首 fixture污染 index exit1及修正、初始 Orca connection／未 focus工具 ack失敗均留原 task；Vite／production build、canvas／horizontal原生手勢、pending導航 race及舊 ZIP／live／完整回歸未驗或未重跑。19表全欄／typeof至 shutdown不變；自有服務／ports／owned page清理已獨立核，兩服務 Ctrl+C原 exit1、Node無最終 guard計數，詳見[開發入口](development-baseline/README.md#m1-w3-三截止法人窗口的零落盤驗證入口)。新測試附件／raw／tmp／DB／artifact0，不能推定全 cache或歷史殘留0。

下一步為統籌接受七檔文件→freeze→本輪索引／coverage→核准 commit及核對→另准 master本地 FF merge→新輪可見統籌／外部清理接手；均未執行。W4來源 gate先由下一輪核，不降低真實性／磁碟／執行條件；不在本輪續取新來源。

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
