# 協作與接手狀態

流程與角色配置由 [AGENTS](../AGENTS.md) 管理；能力與優先順序見 [ROADMAP](ROADMAP.md)，工作完成條件見 [執行清單](ROADMAP_EXECUTION.md)。

## 目前：M1-W4 法人窗口較早截止新產品輪

2026-10-04，本輪由最新已驗收 master `c6018e3f9c1e24aa30db217e4b067a0586e4fb30` 建立新 branch／Orca worktree及統籌、三 child。完整 runtime／Git／自核接手及正式可見 `/subagents` gate已通過，只沿本組 child；舊統籌只補 receipt、不再派工。**W4新增真來源、23日曆／四截止48 net、actual API與兩股各四 cutoff可信原生表單已有限接受；完整 M1未完成。** 兩股窄版8/31原列、6488範圍外截止拒用／恢復、TWSE route拒用及actual服務清理亦已接受，W4批次有限接受。文件驗收／freeze／index／commit／merge仍 pending。

共同 cwd／worktree：`C:/Users/YiCheng/orca/workspaces/taiwan-stock-research/roadmap-m1-window-earlier-cutoff-20261004`；branch：`roadmap-m1-window-earlier-cutoff-20261004`；repo：`C:/Users/YiCheng/Desktop/taiwan-stock-research`；common Git dir：`C:/Users/YiCheng/Desktop/taiwan-stock-research/.git`。四者實際 cwd／Git根、起始 HEAD／master均已核；啟動時 Git乾淨，W3前輪15 blobs及本輪基底 SHA一致。

本輪可見 terminal `term_688fc1a0-b898-4d00-96c4-1a9f8e52678d`已核 connected／writable／non-orphaned及 GPT-6.1-Sol／ultra。上一統籌在 root及三 child idle時實送 `/subagents`，`source=screen`列 Main [current/default]及三 child，四 ID與下表／runtime／parent一致；`No sub-agents running`只是 idle，已 Esc回 Main、未切 child，正式 receipt接受。

唯一 `start-coordinator`初次 exit1：`Timed out waiting for terminal handle after creation`，當時未送 task／無handle；原請求遲延產生本 terminal。Trust一次後核原 root idle／turns=[]／visible／Git，再 structured UTF-8唯一一次 `turn/start`（`01a10716-7add-7c72-b9c5-2c2a6a0bbd2c`），無另 launch／resume或繞 gate。首 task14800B／10057chars／SHA256=`aa00385e67f70d814d1b53f299e11490dfab31307a55bf5da6925342d1b51082`全文一致；三次 `fork_turns=none`與實際 rollout相符。原錯與詳細命令留 task。

空白 shell `term_951c6bb9-606c-4025-9271-d6215a650413`由前輪統籌 exact close `--tab`一次，`ptyKilled=false`；後驗 list=[]、orphaned=true、connected／writable=false、exitCause=`operator_close`。不稱 PTY已kill、不重試。

| 角色 | Thread ID／實際配置 | 白名單與接手 |
| --- | --- | --- |
| 統籌 | `01a10715-32d9-79c3-9aec-c94f60dc6dee`；`gpt-6.1-sol`／`ultra` | 正式承接 W4自主產品及 W3外清；已接受W4有限來源／產品批次及清理；待文件驗收後freeze。 |
| 程式 | `01a10719-9960-7122-8b43-782950e629c3`；`gpt-6.1-sol`／`xhigh` | B1 exact8檔已有限接受：下方四個 backend、三個 frontend及 preview；不取得／實作 W5或自行擴 scope。 |
| 文件 | `01a1071a-1dfb-7af3-ae4e-a71adb58e662`；`gpt-6.1-sol`／`xhigh` | DOC-FINAL-1 exact7既有文件：SOURCE_REGISTRY、DATA_SOURCES、ROADMAP、ROADMAP_EXECUTION、STOCK_RESEARCH_PAGE、development-baseline/README、TASK；交付即停寫待驗收。 |
| 索引與 Git commit | `01a1071a-a400-7542-a56e-75becdb0d472`；`gpt-6-luna`／`medium` | 零來源寫入；W3 exact外清已接受。本輪文件接受／freeze後才刷新／驗 coverage，commit及本地merge分別等核准，目前未執行。 |

四者 `forkedFromId=null`、runtime `sessionId`均為 root ID。Root `parentThreadId=null`、source=`vscode`；三 child的 parent及 `source.subAgent.thread_spawn.parent_thread_id`均為 root，source depth=1、agent_path依序 `/root/program`／`/root/documents`／`/root/index_git`。Root及各 child實際 Rpc `thread/read`、Git及接手核通，不由設定／prompt推定。

B1檔案：`backend/app/institutional_windows.py`、`backend/app/stock_overview.py`、`backend/worker/tpex_institutional_window.py`、`backend/tests/test_institutional_windows.py`、`frontend/src/types.ts`、`frontend/src/components/StockOverview.tsx`、`frontend/src/components/StockOverview.test.tsx`、`tools/institutional-window-preview.cjs`。

App MCP connected，W3六區已 exact清理，現 master原根8區，本輪新根未索引。master docs七檔 coverage為 `complete/no_recorded_issue`、`metadata_changed`；已採新根原文，原根 coverage不證本輪 fresh／完整，不中途刷新或複製索引。

正式既有文書7檔預核淨增≤約100 KiB、TASK≤24 KiB、UTF-8無 BOM／LF；精簡非保護歷史段，不新增附件／backup／helper／manifest。GPG原兩段與「未解驗證與資源限制」至EOF逐 byte保留。繼承零新增測試附件／raw／ZIP／DB／tmp／cache／pycache／log／artifact限制，真原件只存 process memory；不把附件0稱全cache0。Bootstrap／文書不算實作批次。

## 版本接手與指定 W3清理

W3的15檔 FREEZE-W3-1／index coverage／commit／master本地FF已接受，版本為本輪基底 `c6018e3f9c1e24aa30db217e4b067a0586e4fb30`；正式交接／原 task最終 receipt覆蓋歷史 pending，不為 hash反覆提交。舊輪 worktree／branch `roadmap-m1-window-cutoff-expansion-20261004`，root `01a10690-dce1-7e81-901c-4051c657d2e5`，child `01a10695-0577-7450-ac80-85d1d6263cc5`／`01a10695-9514-7aa3-b1ef-aa960a0e3d7d`／`01a10696-22b1-7502-aa33-8da59d536742`，terminal `term_3ed777be-064c-4a05-8492-0b3ae2134ddd`，只作歷史／清理辨識，不恢復角色。

CLEAN-W3指定清理已接受：核舊四 idle、clean／merged及 exact範圍後，terminal一次 close、`ptyKilled=true`且後驗缺席；root一次 archive舊 root及 descendants，四 thread均 archived／notLoaded、歷史保留。Orca exact worktree／branch一次移除 exit0／removed=true，兩者缺席；6 index ID逐一delete一次／status deleted，App後驗僅原 master8。六區前綴 `taiwan-stock-research-roadmap-m1-window-cutoff-expansion-20261004-`，suffix backend-app／backend-worker／backend-tests／frontend-src／tools／docs；6 DB及18個固定 -wal／-shm／-journal exact路徑均後驗缺席。Stage／其他aux及全cache未核清、不擴掃；GPG1232B及原 NO-RETRY不變。Owner allowlist／path比較及只讀後驗原失敗留 task，不追認未跑 gate或改exit。

更早 W1／W2的19檔版本 `f716526ddcd98ddbaa155c2fd9fe70f776ed4e2a`及其指定外清已接受；原舊 root／branch、六區 DB／固定aux缺席，其他aux unknown及當時 logs刪前gate缺口保留原 task。P6d `0f8ac4a`／P6e `5ae84d2`是可靠性歷史；原 roster／可見終端及驗收界線查 Git／原task與[個股頁 §17](STOCK_RESEARCH_PAGE.md#17-m3-p6e個股特徵籌碼獨立區塊讀回隔離)，不沿用其角色。獨立29份文件精簡 `1596fe1`及唯一 ROADMAP P2修正 `7b3212a`已結案，不算產品批次。

## 本輪成果、下一核心與跨輪停滯

| 接手項目 | 狀態與完成條件 |
| --- | --- |
| W4核心操作 | 同兩股新增9/29、保留9/30／10/1／10/2；八組可信原生表單的48 net、5／20日起迄及missing0已有限接受。6488原生9/28清舊值／button0及9/29恢復held值、兩股窄版8/31原列及TWSE route拒用已接受；六組source outer SUMMARY原生展開，20個required日列／日期及合計1080 raw欄另以DOM/textContent核對（含未原生展開子表）。 |
| 真依賴解除 | 新8/31 daily903列／兩股44金融欄及8月21列全 OHLC probe2 GET／146823B已接受。Production firstactual POST3105／9/29另取26原件／3337874B，23 daily共20763全列／46 selected／1012金融欄、三月43 index列與完整23日曆、48 net及1800重複API字串已核；8月20界線前列已驗但未採用。詳述集中[來源 §15](SOURCE_REGISTRY.md#15-m1-w4四截止法人來源與全月日曆核對)。 |
| 實作／測試界線 | 版本／pins／calendar及缺日拒用見來源§15，具名操作見[個股頁 §20](STOCK_RESEARCH_PAGE.md#20-m1-w4四截止法人窗口與原件追溯)，入口／原API exit1與局部補驗見[開發文件](development-baseline/README.md#m1-w4-四截止法人窗口的零落盤驗證入口)。19表／guards核通；不稱完整回歸、保存／跨程序重播、PIT、研究條件或完整M1通過。 |
| 本批分報 | 核心操作增量＝兩股新增9/29並原生切四截止；真依賴＝新兩原件及23日曆／四截止來源→計算→API／UI；可靠性0。W4批次已有限接受，文件驗收待核；停滯維持0。 |
| 下一單一核心 M1-W5 | 同兩股新增2026-09-24、保留四 cutoff，原生切五截止共60 net。免費可執行候選 dataset11856 `d=115/08/28`尚未取得／准入；8月 index的8/28 OHLC已正面核，但 W4未採此日曆／daily。下輪先核8/28全25欄／全列、兩股各22金融欄／關係及新版calendar／policy／pins。 |
| W5候選範圍與完成條件 | 有界8/28～10/2候選24 sessions、最多27 requests＝3 index＋24 daily；9/24需恰20 sessions、5日起9/18／20日起8/28，均待新來源／版本gate驗。Gate後才exact實作、獨立60 net與 native五截止／缺日／來源操作；不在W4取得或實作W5、不沿舊pins放行。 |
| 改選／等待 | 無正面可執行新來源路徑時，由新證據改選必要來源／availability、decision／execution、版本、tick／費稅／合法時段及磁碟保存／跨程序讀回gate齊備的最小M3；仍無可交付項則等待，不空轉或重複審查。 |
| 繼承停滯 | P6d／P6e當時至少2批無核心進度，更早未知；W1真依賴重置0，W2／W3真操作後仍0。W4真依賴／主要操作接受維持0，不因換輪／session／bootstrap／文書／索引或提交重置。 |

W1／W2／W3已接受範圍與數值／原生邊界保留[來源 §13–15](SOURCE_REGISTRY.md#13-m1-w1tpex-多日法人與完整有界交易日)、[個股頁 §18–20](STOCK_RESEARCH_PAGE.md#18-m1-w2同截止法人窗口與原件追溯)及 Git／原 task。完整 M1、範圍外日期／標的／TWSE、PIT／修訂、研究條件／保存仍缺。Actual自有page／API／Node／esbuild／helper及8781／8782 listeners已核清，兩serve原exit1、API DB preserved／guard0，Node finalcounter與esbuild exit未知。下一步文件接受→freeze→索引／coverage→核准commit及核對→另准master本地merge，現均 pending；新輪須獨立可見啟動／接手與外部清理 gate。

### 新繼承的 GPG 殘留與簽章收據更正

本輪新NO-RETRY殘留/流程錯誤：Git提交前索引角色未預先核落盤即跑C:/Program Files/Git/usr/bin/gpg.exe --list-secret-keys --with-colons，merged診斷明示directory/keybox/trustdb created、exit0無secretrecords，但未分stdout/stderr/未先核absent/無ownedPID證明。新C:/Users/YiCheng/.gnupg/pubring.kbx32B與trustdb.gpg1200B、父.gnupg目錄仍存在；root限定目录只读核仅2子、所有祖先owner/nonreparse。CLEAN-GPG-W3-1 exact2files1232B+新空目錄清理被automatic approval review於CreateProcess前拒，理由只有blocked by policy，0程序/0刪；被拒腳本exclusive/predelete checks未執行，不補通過。NO-RETRY不換root/角色/命令重試，不掃profile或killgpgdaemon；功能/索引有效、不重跑。根據既有本地commit授權，root僅批准單命令git -c commit.gpgsign=false commit，不改repo/global簽章設定、不再gpg。此新未核落盤錯誤/拒絕殘留須在你初始TASK接手狀態原文如實納入，原歷史NO-RETRY尾段仍逐字保留。

簽章需求收據更正：C1原git config --show-origin --get commit.gpgsign實際stdout空、exit1；filtered gpg/signing讀取也空，沒有true/origin/scope。索引角色先前聲稱repo commit.gpgsign=true是誤判，已撤回。GPG查詢本不必要；root一度依錯回報加asserttrue只讀核末尾exit1，已修正為實際local/global unset收據exit0，不稱config曾true或C2改了設定。C2唯一命令-c commit.gpgsign=false未寫repo/globalconfig，commit有效。新NO-RETRY1232B/profile殘留與未預核落盤/自動拒絕仍原樣繼承。

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
